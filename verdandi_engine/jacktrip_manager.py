"""
JackTrip session manager for audio links.
Handles spawning and lifecycle of JackTrip client processes.
"""
import asyncio
import structlog
from typing import Dict, Optional, Tuple
from pathlib import Path
import shutil

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database

logger = structlog.get_logger()


class JackTripSession:
    """Represents a running JackTrip client process."""
    
    def __init__(
        self, 
        link_id: str,
        process: asyncio.subprocess.Process,
        remote_host: str,
        remote_port: int,
        channels: int,
        mode: str
    ):
        self.link_id = link_id
        self.process = process
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.channels = channels
        self.mode = mode
        self.jack_client_name = f"verdandi_jacktrip_{link_id[:8]}"
        
    async def wait(self):
        """Wait for process to exit and return exit code."""
        return await self.process.wait()
        
    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process.returncode is None
        
    async def terminate(self, timeout: float = 5.0):
        """Gracefully terminate the JackTrip process."""
        if not self.is_running():
            return
            
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "jacktrip_graceful_shutdown_timeout",
                link_id=self.link_id,
                pid=self.process.pid
            )
            self.process.kill()
            await self.process.wait()


class JackTripManager:
    """
    Manages JackTrip client processes for audio links.
    
    Responsibilities:
    - Spawn JackTrip clients in P2P or hub-client mode
    - Monitor process health
    - Clean up on link removal
    """
    
    def __init__(self, config: VerdandiConfig, database: Database):
        self.config = config
        self.database = database
        self.sessions: Dict[str, JackTripSession] = {}
        self.jacktrip_path: Optional[Path] = None
        
    async def initialize(self):
        """Find jacktrip executable and validate environment."""
        # Locate jacktrip binary
        jacktrip_bin = shutil.which("jacktrip")
        if not jacktrip_bin:
            logger.warning("jacktrip_not_found", hint="Install with: sudo apt install jacktrip")
            return
            
        self.jacktrip_path = Path(jacktrip_bin)
        logger.info("jacktrip_manager_initialized", jacktrip_path=str(self.jacktrip_path))
        
    async def create_audio_link(
        self, 
        link_id: str,
        remote_host: str,
        remote_port: int,
        channels: int = 2,
        mode: str = "p2p",
        sample_rate: int = 48000,
        buffer_size: int = 128
    ) -> bool:
        """
        Create an audio link by spawning a JackTrip client.
        
        Args:
            link_id: Link UUID
            remote_host: Remote node IP address
            remote_port: Remote JackTrip port (UDP)
            channels: Number of audio channels (default 2)
            mode: "p2p" for peer-to-peer, "hub" for hub-client
            sample_rate: JACK sample rate in Hz (must match all nodes, default 48000)
            buffer_size: JACK buffer size in frames (must match all nodes, default 128)
            
        Returns:
            True if session started successfully
        """
        if not self.jacktrip_path:
            logger.error("jacktrip_unavailable", link_id=link_id)
            return False
            
        if link_id in self.sessions:
            logger.warning("jacktrip_session_already_exists", link_id=link_id)
            return False
            
        # Build jacktrip command
        # -c = client mode (connects to server)
        # -n = number of channels
        # --clientname = JACK client name
        jack_client_name = f"verdandi_jacktrip_{link_id[:8]}"
        
        cmd = [
            str(self.jacktrip_path),
            "-c", remote_host,
            "-n", str(channels),
            "--clientname", jack_client_name,
            "--udprt",  # Use UDP with real-time thread
            "-F", str(buffer_size),  # JACK buffer size
            "-q", "4",  # Queue buffer length (4 packets default)
            # Note: JackTrip uses JACK's sample rate automatically
        ]
        
        # Add port if non-default
        if remote_port != 4464:
            cmd.extend(["-o", "udp", "-p", str(remote_port)])
            
        logger.info(
            "starting_jacktrip_client",
            link_id=link_id,
            remote_host=remote_host,
            remote_port=remote_port,
            channels=channels,
            mode=mode,
            command=" ".join(cmd)
        )
        
        try:
            # Spawn JackTrip process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            # Give it a moment to start and connect
            await asyncio.sleep(0.5)
            
            # Check if it's still running
            if process.returncode is not None:
                stdout, stderr = await process.communicate()
                logger.error(
                    "jacktrip_failed_to_start",
                    link_id=link_id,
                    exit_code=process.returncode,
                    stderr=stderr.decode()[:500]
                )
                return False
                
            # Create session object
            session = JackTripSession(
                link_id=link_id,
                process=process,
                remote_host=remote_host,
                remote_port=remote_port,
                channels=channels,
                mode=mode
            )
            
            self.sessions[link_id] = session
            
            # Start monitoring task
            asyncio.create_task(self._monitor_session(session))
            
            logger.info(
                "jacktrip_session_started",
                link_id=link_id,
                pid=process.pid,
                jack_client_name=jack_client_name
            )
            
            return True
            
        except Exception as e:
            logger.error("jacktrip_spawn_error", link_id=link_id, error=str(e))
            return False
            
    async def remove_audio_link(self, link_id: str) -> bool:
        """
        Remove an audio link by terminating the JackTrip process.
        
        Args:
            link_id: Link UUID
            
        Returns:
            True if session was terminated successfully
        """
        session = self.sessions.get(link_id)
        if not session:
            logger.warning("jacktrip_session_not_found", link_id=link_id)
            return False
            
        logger.info("stopping_jacktrip_session", link_id=link_id, pid=session.process.pid)
        
        await session.terminate()
        del self.sessions[link_id]
        
        logger.info("jacktrip_session_stopped", link_id=link_id)
        return True
        
    async def get_link_status(self, link_id: str) -> Tuple[bool, Optional[str]]:
        """
        Get the status of an audio link.
        
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
            
    async def _monitor_session(self, session: JackTripSession):
        """
        Background task to monitor a JackTrip session.
        Updates database if process crashes.
        """
        try:
            exit_code = await session.wait()
            
            logger.warning(
                "jacktrip_session_exited",
                link_id=session.link_id,
                exit_code=exit_code,
                pid=session.process.pid
            )
                    
            # Clean up
            if session.link_id in self.sessions:
                del self.sessions[session.link_id]
                
        except Exception as e:
            logger.error(
                "jacktrip_monitor_error",
                link_id=session.link_id,
                error=str(e)
            )
            
    async def shutdown(self):
        """Shutdown all JackTrip sessions."""
        logger.info("shutting_down_jacktrip_manager", active_sessions=len(self.sessions))
        
        # Terminate all sessions in parallel
        tasks = [
            session.terminate()
            for session in self.sessions.values()
        ]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
        self.sessions.clear()
        logger.info("jacktrip_manager_shutdown_complete")
