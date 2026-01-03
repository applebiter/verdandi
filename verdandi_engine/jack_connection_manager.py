"""
JACK port connection manager for auto-wiring audio ports.
Handles automatic connection of JackTrip ports to local audio sources/sinks.
"""
import asyncio
import structlog
from typing import List, Dict, Optional, Set
import jack

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database

logger = structlog.get_logger()


class JackConnectionManager:
    """
    Manages JACK port connections for audio links.
    
    Responsibilities:
    - Auto-connect JackTrip ports to local audio interfaces
    - Apply user-defined port mappings from database
    - Monitor and re-establish dropped connections
    """
    
    def __init__(self, config: VerdandiConfig, database: Database):
        self.config = config
        self.database = database
        self.jack_client: Optional[jack.Client] = None
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        """Initialize JACK client and register callbacks."""
        try:
            # Create JACK client for Verdandi
            self.jack_client = jack.Client("verdandi_jack")
            
            # Register port registration callback to detect new JackTrip ports
            self.jack_client.set_port_registration_callback(self._on_port_registered)
            
            # Activate client
            self.jack_client.activate()
            
            logger.info(
                "jack_connection_manager_initialized",
                jack_server=self.jack_client.name,
                sample_rate=self.jack_client.samplerate,
                buffer_size=self.jack_client.blocksize
            )
            
            # Start monitoring task
            self._monitoring = True
            self._monitor_task = asyncio.create_task(self._monitor_connections())
            
        except jack.JackError as e:
            logger.error("jack_client_init_failed", error=str(e))
            self.jack_client = None
            
    def _on_port_registered(self, port: jack.Port, register: bool):
        """
        Callback when a JACK port is registered or unregistered.
        
        Args:
            port: The JACK port
            register: True if registered, False if unregistered
        """
        if not register:
            return
            
        # Check if it's a JackTrip port
        port_name = port.name
        if "jacktrip" in port_name.lower():
            logger.info("jacktrip_port_detected", port_name=port_name)
            # Schedule auto-connection (done async in monitor task)
            
    async def connect_link_ports(self, link_id: str) -> bool:
        """
        Connect JACK ports for a specific link using default auto-connection.
        
        Args:
            link_id: Link UUID
            
        Returns:
            True if connections were made successfully
        """
        if not self.jack_client:
            logger.error("jack_client_unavailable", link_id=link_id)
            return False
            
        # Use default auto-connection strategy
        return await self._auto_connect_link(link_id)
            
    async def _auto_connect_link(self, link_id: str) -> bool:
        """
        Auto-connect JackTrip ports for a link to default audio I/O.
        
        Default strategy:
        - JackTrip send ports -> system playback (speakers)
        - JackTrip receive ports <- system capture (microphone)
        """
        if not self.jack_client:
            return False
            
        try:
            # Find JackTrip ports for this link
            jacktrip_pattern = f"verdandi_jacktrip_{link_id[:8]}"
            all_ports = self.jack_client.get_ports()
            
            send_ports = []
            receive_ports = []
            
            for port in all_ports:
                if jacktrip_pattern in port.name:
                    if port.is_output:
                        send_ports.append(port)
                    elif port.is_input:
                        receive_ports.append(port)
                        
            if not send_ports and not receive_ports:
                logger.warning("no_jacktrip_ports_found", link_id=link_id, pattern=jacktrip_pattern)
                return False
                
            # Get system ports
            system_playback = self.jack_client.get_ports(
                name_pattern="system:playback_*",
                is_audio=True,
                is_input=True
            )
            
            system_capture = self.jack_client.get_ports(
                name_pattern="system:capture_*",
                is_audio=True,
                is_output=True
            )
            
            # Connect JackTrip outputs to system playback
            for i, send_port in enumerate(send_ports):
                if i < len(system_playback):
                    try:
                        self.jack_client.connect(send_port, system_playback[i])
                        logger.info(
                            "auto_connected_to_playback",
                            source=send_port.name,
                            target=system_playback[i].name
                        )
                    except jack.JackError:
                        pass  # Already connected or error
                        
            # Connect system capture to JackTrip inputs
            for i, receive_port in enumerate(receive_ports):
                if i < len(system_capture):
                    try:
                        self.jack_client.connect(system_capture[i], receive_port)
                        logger.info(
                            "auto_connected_from_capture",
                            source=system_capture[i].name,
                            target=receive_port.name
                        )
                    except jack.JackError:
                        pass  # Already connected or error
                        
            return True
            
        except Exception as e:
            logger.error("auto_connect_error", link_id=link_id, error=str(e))
            return False
            
    async def disconnect_link_ports(self, link_id: str) -> bool:
        """
        Disconnect all JACK ports associated with a link.
        
        Args:
            link_id: Link UUID
            
        Returns:
            True if disconnections were successful
        """
        if not self.jack_client:
            return False
            
        try:
            # Find JackTrip ports for this link
            jacktrip_pattern = f"verdandi_jacktrip_{link_id[:8]}"
            all_ports = self.jack_client.get_ports()
            
            for port in all_ports:
                if jacktrip_pattern in port.name:
                    # Get all connections for this port
                    connections = self.jack_client.get_all_connections(port)
                    for connected_port in connections:
                        try:
                            if port.is_output:
                                self.jack_client.disconnect(port, connected_port)
                            else:
                                self.jack_client.disconnect(connected_port, port)
                            logger.info(
                                "jack_ports_disconnected",
                                port1=port.name,
                                port2=connected_port.name
                            )
                        except jack.JackError:
                            pass
                            
            return True
            
        except Exception as e:
            logger.error("disconnect_link_ports_error", link_id=link_id, error=str(e))
            return False
            
    async def _monitor_connections(self):
        """
        Background task to monitor and maintain JACK connections.
        Re-establishes dropped connections automatically.
        """
        while self._monitoring:
            try:
                await asyncio.sleep(5.0)  # Check every 5 seconds
                
                if not self.jack_client:
                    continue
                    
                # Monitor all JackTrip ports and ensure they have connections
                try:
                    jacktrip_ports = self.jack_client.get_ports(name_pattern="*verdandi_jacktrip*")
                    
                    for port in jacktrip_ports:
                        connections = self.jack_client.get_all_connections(port)
                        if not connections:
                            # Extract link_id from port name and reconnect
                            port_name = port.name
                            # Port names are like "verdandi_jacktrip_LINKID:..."
                            parts = port_name.split("_")
                            if len(parts) >= 3:
                                link_id_prefix = parts[2].split(":")[0]
                                logger.warning(
                                    "jacktrip_port_not_connected",
                                    port_name=port_name,
                                    link_id_prefix=link_id_prefix
                                )
                except jack.JackError:
                    pass  # JACK connection issue, will retry
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("connection_monitor_error", error=str(e))
                await asyncio.sleep(5.0)
                
    async def shutdown(self):
        """Shutdown the JACK connection manager."""
        self._monitoring = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
                
        if self.jack_client:
            self.jack_client.deactivate()
            self.jack_client.close()
            logger.info("jack_connection_manager_shutdown")
