"""
RTP-MIDI session manager for MIDI fabric links.
Handles spawning and lifecycle of rtpmidid processes.
"""
import asyncio
import structlog
from typing import Dict, Optional, Tuple
from pathlib import Path
import shutil

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.models.fabric import FabricLink

logger = structlog.get_logger()


class RTPMidiSession:
    """Represents a running rtpmidid process."""
    
    def __init__(
        self,
        link_id: str,
        process: asyncio.subprocess.Process,
        session_name: str,
        remote_host: str,
        remote_port: int
    ):
        self.link_id = link_id
        self.process = process
        self.session_name = session_name
        self.remote_host = remote_host
        self.remote_port = remote_port
        
    async def wait(self):
        """Wait for process to exit and return exit code."""
        return await self.process.wait()
        
    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process.returncode is None
        
    async def terminate(self, timeout: float = 5.0):
        """Gracefully terminate the rtpmidid process."""
        if not self.is_running():
            return
            
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "rtpmidi_graceful_shutdown_timeout",
                link_id=self.link_id,
                pid=self.process.pid
            )
            self.process.kill()
            await self.process.wait()


class RTPMidiManager:
    """
    Manages rtpmidid processes for MIDI fabric links.
    
    Responsibilities:
    - Spawn rtpmidid clients for network MIDI sessions
    - Monitor process health
    - Clean up on link removal
    """
    
    def __init__(self, config: VerdandiConfig, database: Database):
        self.config = config
        self.database = database
        self.sessions: Dict[str, RTPMidiSession] = {}
        self.rtpmidid_path: Optional[Path] = None
        
    async def initialize(self):
        """Find rtpmidid executable and validate environment."""
        # Locate rtpmidid binary
        rtpmidid_bin = shutil.which("rtpmidid")
        if not rtpmidid_bin:
            logger.warning(
                "rtpmidid_not_found",
                hint="Install with: sudo apt install rtpmidid"
            )
            return
            
        self.rtpmidid_path = Path(rtpmidid_bin)
        logger.info("rtpmidi_manager_initialized", rtpmidid_path=str(self.rtpmidid_path))
        
    async def create_midi_link(
        self,
        link_id: str,
        remote_host: str,
        remote_port: int = 5004,
        session_name: Optional[str] = None
    ) -> bool:
        """
        Create a MIDI link by spawning an rtpmidid client.
        
        Args:
            link_id: Fabric link UUID
            remote_host: Remote node IP address
            remote_port: Remote RTP-MIDI port (default 5004)
            session_name: MIDI session name (auto-generated if None)
            
        Returns:
            True if session started successfully
        """
        if not self.rtpmidid_path:
            logger.error("rtpmidid_unavailable", link_id=link_id)
            return False
            
        if link_id in self.sessions:
            logger.warning("rtpmidi_session_already_exists", link_id=link_id)
            return False
            
        # Generate session name if not provided
        if not session_name:
            session_name = f"verdandi_{link_id[:8]}"
            
        # Build rtpmidid command
        # --name = session name (creates ALSA sequencer port)
        # --connect = connect to remote host:port
        cmd = [
            str(self.rtpmidid_path),
            "--name", session_name,
            "--connect", f"{remote_host}:{remote_port}"
        ]
        
        logger.info(
            "starting_rtpmidi_client",
            link_id=link_id,
            remote_host=remote_host,
            remote_port=remote_port,
            session_name=session_name,
            command=" ".join(cmd)
        )
        
        try:
            # Spawn rtpmidid process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            # Give it a moment to start
            await asyncio.sleep(0.5)
            
            # Check if it's still running
            if process.returncode is not None:
                stdout, stderr = await process.communicate()
                logger.error(
                    "rtpmidi_failed_to_start",
                    link_id=link_id,
                    exit_code=process.returncode,
                    stderr=stderr.decode()[:500]
                )
                return False
                
            # Create session object
            session = RTPMidiSession(
                link_id=link_id,
                process=process,
                session_name=session_name,
                remote_host=remote_host,
                remote_port=remote_port
            )
            
            self.sessions[link_id] = session
            
            # Start monitoring task
            asyncio.create_task(self._monitor_session(session))
            
            logger.info(
                "rtpmidi_session_started",
                link_id=link_id,
                pid=process.pid,
                session_name=session_name
            )
            
            return True
            
        except Exception as e:
            logger.error("rtpmidi_spawn_error", link_id=link_id, error=str(e))
            return False
            
    async def remove_midi_link(self, link_id: str) -> bool:
        """
        Remove a MIDI link by terminating the rtpmidid process.
        
        Args:
            link_id: Fabric link UUID
            
        Returns:
            True if session was terminated successfully
        """
        session = self.sessions.get(link_id)
        if not session:
            logger.warning("rtpmidi_session_not_found", link_id=link_id)
            return False
            
        logger.info("stopping_rtpmidi_session", link_id=link_id, pid=session.process.pid)
        
        await session.terminate()
        del self.sessions[link_id]
        
        logger.info("rtpmidi_session_stopped", link_id=link_id)
        return True
        
    async def get_link_status(self, link_id: str) -> Tuple[bool, Optional[str]]:
        """
        Get the status of a MIDI link.
        
        Returns:
            (is_active, status_message)
        """
        session = self.sessions.get(link_id)
        if not session:
            return False, "Session not found"
            
        if session.is_running():
            return True, f"Active (PID: {session.process.pid})"
        else:
            return False, f"Terminated (exit code: {session.process.returncode})"
            
    async def _monitor_session(self, session: RTPMidiSession):
        """
        Background task to monitor an RTP-MIDI session.
        Updates database if process crashes.
        """
        try:
            exit_code = await session.wait()
            
            logger.warning(
                "rtpmidi_session_exited",
                link_id=session.link_id,
                exit_code=exit_code,
                pid=session.process.pid
            )
            
            # Update database to mark link inactive
            db = self.database.get_session()
            try:
                from verdandi_codex.models.fabric import LinkStatus
                
                link = db.get(FabricLink, session.link_id)
                if link:
                    link.status = LinkStatus.DOWN
                    db.commit()
            finally:
                db.close()
                    
            # Clean up
            if session.link_id in self.sessions:
                del self.sessions[session.link_id]
                
        except Exception as e:
            logger.error(
                "rtpmidi_monitor_error",
                link_id=session.link_id,
                error=str(e)
            )
            
    async def shutdown(self):
        """Shutdown all RTP-MIDI sessions."""
        logger.info("shutting_down_rtpmidi_manager", active_sessions=len(self.sessions))
        
        # Terminate all sessions in parallel
        tasks = [
            session.terminate()
            for session in self.sessions.values()
        ]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
        self.sessions.clear()
        logger.info("rtpmidi_manager_shutdown_complete")
