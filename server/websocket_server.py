"""WebSocket server for ALARA UI integration."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import websockets
from dotenv import load_dotenv
from loguru import logger

from alara.core.goal_understander import GoalUnderstander
from alara.core.orchestrator import Orchestrator
from alara.core.planner import Planner, PlanningError
from alara.memory import MemoryManager
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import TaskGraph


class AlaraWebSocketServer:
    """WebSocket server for ALARA UI communication."""
    
    HOST = "localhost"
    PORT = 8765
    
    def __init__(self) -> None:
        """Initialize the WebSocket server."""
        load_dotenv()
        self.memory = MemoryManager.get_instance()
        self.understander = GoalUnderstander()
        self.planner = Planner()
        self.orchestrator = Orchestrator()
        
        self._current_task_graph: TaskGraph | None = None
        self._current_goal_context: GoalContext | None = None
        self._current_raw_goal: str = ""
        self._current_entry_id: str | None = None
        self._connected_client = None
        self._loop = None
        
        logger.info("AlaraWebSocketServer initialized")
    
    async def start(self) -> None:
        """Start the WebSocket server."""
        self._loop = asyncio.get_event_loop()
        
        async def handler(websocket):
            await self._handler(websocket)
        
        server = await websockets.serve(handler, self.HOST, self.PORT)
        logger.info(f"Listening on ws://{self.HOST}:{self.PORT}")
        
        # Run forever
        shutdown_event = asyncio.Event()
        try:
            await shutdown_event.wait()  # This will keep the server running
        except asyncio.CancelledError:
            logger.info("Server shutdown requested")
    
    async def _handler(self, websocket) -> None:
        """Handle WebSocket connections."""
        self._connected_client = websocket
        logger.info("Client connected")
        
        try:
            # Send initial status
            await self._send(websocket, {
                "type": "status",
                "message": "Alara ready."
            })
            
            # Handle messages
            async for raw_message in websocket:
                await self._handle_message(websocket, raw_message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("Client disconnected")
        except Exception as e:
            logger.error(f"WebSocket handler error: {e}")
    
    async def _handle_message(self, websocket, raw: str) -> None:
        """Handle incoming messages."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(websocket, {
                "type": "error",
                "message": "Invalid JSON message"
            })
            return
        
        msg_type = msg.get("type")
        
        if msg_type == "goal_submit":
            await self._handle_goal_submit(websocket, msg)
        elif msg_type == "goal_confirm":
            await self._handle_goal_confirm(websocket, msg)
        elif msg_type == "goal_cancel":
            await self._handle_goal_cancel(websocket, msg)
        elif msg_type == "ping":
            await self._send(websocket, {"type": "pong"})
        else:
            await self._send(websocket, {
                "type": "error",
                "message": f"Unknown message type: {msg_type}"
            })
    
    async def _handle_goal_submit(self, websocket, msg: dict) -> None:
        """Handle goal submission."""
        goal = msg.get("goal", "").strip()
        
        if not goal:
            await self._send(websocket, {
                "type": "error",
                "message": "Goal cannot be empty"
            })
            return
        
        try:
            # Send planning state
            await self._send(websocket, {"type": "state", "state": "planning"})
            
            # Run goal understanding
            goal_context = await self._run_in_executor(
                self.understander.understand, goal
            )
            
            # Build memory context
            memory_context = await self._run_in_executor(
                self.memory.build_context, goal, goal_context
            )
            
            # Plan the task
            task_graph = await self._run_in_executor(
                self.planner.plan, goal_context, memory_context
            )
            
            # Store state
            self._current_goal_context = goal_context
            self._current_task_graph = task_graph
            self._current_raw_goal = goal
            
            # Send plan ready message
            await self._send(websocket, {
                "type": "plan_ready",
                "goal": goal_context.goal,
                "steps": [
                    {
                        "id": step.id,
                        "description": step.description,
                        "operation": step.operation,
                        "step_type": step.step_type.value,
                        "verification": step.verification_method,
                        "deps": step.depends_on
                    }
                    for step in task_graph.steps
                ],
                "scope": goal_context.scope,
                "complexity": goal_context.estimated_complexity,
                "step_count": len(task_graph.steps)
            })
            
        except PlanningError as e:
            await self._send(websocket, {
                "type": "error",
                "message": f"Planning failed: {e}"
            })
            self._clear_state()
        except Exception as e:
            logger.error(f"Goal submit error: {e}")
            await self._send(websocket, {
                "type": "error",
                "message": "Internal error during planning"
            })
            self._clear_state()
    
    async def _handle_goal_confirm(self, websocket, msg: dict) -> None:
        """Handle goal confirmation for execution."""
        if not self._current_task_graph:
            await self._send(websocket, {
                "type": "error",
                "message": "No plan to execute"
            })
            return
        
        try:
            # Send execution started
            await self._send(websocket, {
                "type": "execution_started",
                "total_steps": len(self._current_task_graph.steps)
            })
            
            # Start session tracking
            entry_id = self.memory.session.start_goal(
                self._current_raw_goal,
                self._current_goal_context
            )
            self._current_entry_id = entry_id
            
            # Track execution time
            start_time = time.monotonic()
            
            # Define progress callback
            def progress_callback(step, step_result):
                # Count completed steps
                steps_done = sum(
                    1 for s in self._current_task_graph.steps
                    if s.status.value == "done"
                )
                steps_total = len(self._current_task_graph.steps)
                
                progress_msg = {
                    "type": "step_progress",
                    "step_id": step.id,
                    "operation": step.operation,
                    "description": step.description,
                    "status": step.status.value,
                    "steps_done": steps_done,
                    "steps_total": steps_total,
                    "progress_pct": int((steps_done / steps_total) * 100)
                }
                
                # Send progress update thread-safely
                asyncio.run_coroutine_threadsafe(
                    websocket.send(json.dumps(progress_msg)),
                    self._loop
                ).result(timeout=5)
            
            # Run orchestration
            result = await self._run_in_executor(
                self.orchestrator.run,
                self._current_task_graph,
                progress_callback
            )
            
            # Calculate duration
            duration_ms = (time.monotonic() - start_time) * 1000
            
            # Update memory after execution
            self.memory.after_execution(
                self._current_raw_goal,
                self._current_goal_context,
                self._current_task_graph,
                result,
                entry_id,
                duration_ms
            )
            
            # Send completion message
            await self._send(websocket, {
                "type": "execution_complete",
                "success": result.success,
                "steps_completed": result.steps_completed,
                "steps_failed": result.steps_failed,
                "steps_skipped": result.steps_skipped,
                "total_steps": result.total_steps,
                "message": result.message
            })
            
            # Clear state
            self._clear_state()
            
        except Exception as e:
            logger.error(f"Goal confirm error: {e}")
            await self._send(websocket, {
                "type": "error",
                "message": "Internal error during execution"
            })
            self._clear_state()
    
    async def _handle_goal_cancel(self, websocket, msg: dict) -> None:
        """Handle goal cancellation."""
        self._clear_state()
        await self._send(websocket, {"type": "state", "state": "idle"})
        logger.info("Goal cancelled")
    
    async def _send(self, websocket, message: dict) -> None:
        """Send a message to the WebSocket client."""
        try:
            await websocket.send(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send message: {e}")
    
    def _clear_state(self) -> None:
        """Clear current task state."""
        self._current_task_graph = None
        self._current_goal_context = None
        self._current_raw_goal = ""
        self._current_entry_id = None
    
    async def _run_in_executor(self, fn, *args):
        """Run a function in the thread pool executor."""
        return await self._loop.run_in_executor(None, fn, *args)


def run() -> None:
    """Run the WebSocket server."""
    server = AlaraWebSocketServer()
    asyncio.run(server.start())


if __name__ == "__main__":
    run()
