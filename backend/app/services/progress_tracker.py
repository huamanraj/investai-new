"""
Progress Tracker for Background Jobs
Manages real-time progress updates and SSE streaming
"""
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List, Set
from collections import defaultdict

from app.core.logging import console_logger


class ProgressTracker:
    """
    Track and broadcast job progress updates in real-time.
    Supports multiple subscribers per job.
    """
    
    def __init__(self):
        # Store progress updates: {job_id: [list of progress events]}
        self._progress_store: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Store active subscribers: {job_id: [list of queues]}
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        
        # Track completed/failed/cancelled jobs: {job_id: final_status}
        self._finished_jobs: Dict[str, str] = {}
        
        # Max events to store per job (to prevent memory leaks)
        self.max_events_per_job = 100
        
        # Keep finished job status for 5 minutes (for late subscribers)
        self.finished_job_ttl_seconds = 300
    
    async def emit(
        self,
        job_id: str,
        event_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        step: Optional[str] = None,
        step_index: Optional[int] = None,
        total_steps: Optional[int] = None
    ):
        """
        Emit a progress update event.
        
        Args:
            job_id: Job identifier
            event_type: Type of event (started, progress, completed, error, etc.)
            message: Human-readable message
            data: Additional data
            step: Current step name
            step_index: Current step index (0-based)
            total_steps: Total number of steps
        """
        event = {
            "type": event_type,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "step": step,
            "step_index": step_index,
            "total_steps": total_steps,
            "progress_percentage": self._calculate_progress(step_index, total_steps),
            "data": data or {}
        }
        
        # Store event
        self._progress_store[job_id].append(event)
        
        # Limit stored events
        if len(self._progress_store[job_id]) > self.max_events_per_job:
            self._progress_store[job_id] = self._progress_store[job_id][-self.max_events_per_job:]
        
        # Mark job as finished if terminal event
        if event_type in ["completed", "error", "cancelled"]:
            self._finished_jobs[job_id] = event_type
            console_logger.info(f"📍 Job {job_id} marked as finished: {event_type}")
        
        # Broadcast to all subscribers
        await self._broadcast(job_id, event)
        
        # Log important events
        if event_type in ["started", "completed", "error", "cancelled"]:
            console_logger.info(f"[{job_id}] {message}")
    
    def _calculate_progress(
        self,
        step_index: Optional[int],
        total_steps: Optional[int]
    ) -> Optional[float]:
        """Calculate progress percentage"""
        if step_index is not None and total_steps and total_steps > 0:
            return round((step_index / total_steps) * 100, 1)
        return None
    
    async def _broadcast(self, job_id: str, event: Dict[str, Any]):
        """Broadcast event to all subscribers"""
        if job_id in self._subscribers:
            # Create list of subscribers to remove (if queue is full or closed)
            to_remove = []
            
            for queue in self._subscribers[job_id]:
                try:
                    # Non-blocking put with small timeout
                    await asyncio.wait_for(queue.put(event), timeout=0.5)
                except (asyncio.TimeoutError, asyncio.QueueFull):
                    # Queue is full, mark for removal
                    to_remove.append(queue)
                except Exception as e:
                    # Queue closed or other error
                    console_logger.debug(f"Failed to broadcast to subscriber: {e}")
                    to_remove.append(queue)
            
            # Remove dead subscribers
            for queue in to_remove:
                try:
                    self._subscribers[job_id].remove(queue)
                except ValueError:
                    pass
    
    def is_job_finished(self, job_id: str) -> Optional[str]:
        """Check if a job is finished and return its final status"""
        return self._finished_jobs.get(job_id)
    
    async def subscribe(self, job_id: str) -> asyncio.Queue:
        """
        Subscribe to progress updates for a job.
        Returns a queue that will receive progress events.
        
        If the job is already finished, the queue will receive the final event immediately.
        """
        queue = asyncio.Queue(maxsize=50)
        self._subscribers[job_id].append(queue)
        
        # Check if job is already finished
        final_status = self._finished_jobs.get(job_id)
        
        if final_status:
            # Job already finished - send final event immediately
            console_logger.info(f"📡 Job {job_id} already finished ({final_status}), sending final event")
            
            # Send the last events including the completion event
            if job_id in self._progress_store:
                for event in self._progress_store[job_id][-5:]:  # Last 5 events
                    try:
                        await queue.put(event)
                    except asyncio.QueueFull:
                        pass
            
            # Ensure we send a terminal event
            await queue.put({
                "type": final_status,
                "message": f"Job {final_status}",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {"already_finished": True}
            })
        else:
            # Send historical events to new subscriber
            if job_id in self._progress_store:
                for event in self._progress_store[job_id][-10:]:  # Last 10 events
                    try:
                        await queue.put(event)
                    except asyncio.QueueFull:
                        pass
        
        return queue
    
    def unsubscribe(self, job_id: str, queue: asyncio.Queue):
        """Unsubscribe from job updates"""
        if job_id in self._subscribers:
            try:
                self._subscribers[job_id].remove(queue)
            except ValueError:
                pass
    
    def get_subscriber_count(self, job_id: str) -> int:
        """Get the number of active subscribers for a job"""
        return len(self._subscribers.get(job_id, []))
    
    def get_recent_events(self, job_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent events for a job"""
        if job_id in self._progress_store:
            return self._progress_store[job_id][-limit:]
        return []
    
    def cleanup_job(self, job_id: str):
        """
        Clean up stored events and subscribers for a completed job.
        Called after job is done and all subscribers have been notified.
        """
        console_logger.info(f"🧹 Cleaning up job {job_id}")
        
        if job_id in self._progress_store:
            del self._progress_store[job_id]
        
        if job_id in self._subscribers:
            # Close all remaining queues by sending a final event
            for queue in self._subscribers[job_id]:
                try:
                    # Clear the queue
                    while not queue.empty():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                except Exception:
                    pass
            
            del self._subscribers[job_id]
        
        # Keep the finished status for a while (so late subscribers know the job is done)
        # It will be cleaned up by periodic cleanup or after TTL
    
    def force_cleanup_job(self, job_id: str):
        """Forcefully clean up all data for a job including finished status"""
        self.cleanup_job(job_id)
        
        if job_id in self._finished_jobs:
            del self._finished_jobs[job_id]
    
    def get_active_jobs(self) -> List[str]:
        """Get list of jobs that have active subscribers"""
        return [job_id for job_id, subs in self._subscribers.items() if len(subs) > 0]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics for debugging"""
        return {
            "total_jobs_tracked": len(self._progress_store),
            "active_subscriptions": sum(len(subs) for subs in self._subscribers.values()),
            "finished_jobs": len(self._finished_jobs),
            "jobs_with_subscribers": len(self.get_active_jobs())
        }


# Global singleton instance
progress_tracker = ProgressTracker()
