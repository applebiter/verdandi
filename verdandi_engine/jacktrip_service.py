"""
gRPC service implementation for JackTrip operations.
"""

import logging
import subprocess
import signal
import os
from typing import Optional

from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc

logger = logging.getLogger(__name__)


class JackTripServicer(verdandi_pb2_grpc.JackTripServiceServicer):
    """Implementation of JackTripService."""
    
    def __init__(self):
        self.hub_process = None
        self.client_process = None
        self.hub_config = {}
        self.client_config = {}
    
    def StartHub(self, request, context):
        """Start JackTrip in hub mode."""
        if self.hub_process and self.hub_process.poll() is None:
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message="Hub already running"
            )
        
        try:
            send_channels = request.send_channels or 2
            receive_channels = request.receive_channels or 2
            sample_rate = request.sample_rate or 48000
            buffer_size = request.buffer_size or 128
            port = request.port or 4464
            
            # Build JackTrip command for hub mode
            cmd = [
                "jacktrip",
                "-S",  # Hub server mode
                "--bindport", str(port)
            ]
            # Note: Hub doesn't specify channels - clients do
            
            logger.info(f"Starting JackTrip hub: {' '.join(cmd)}")
            
            # Start process
            self.hub_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            
            # Store config
            self.hub_config = {
                "send_channels": send_channels,
                "receive_channels": receive_channels,
                "sample_rate": sample_rate,
                "buffer_size": buffer_size,
                "port": port
            }
            
            return verdandi_pb2.JackTripOperationResponse(
                success=True,
                message=f"JackTrip hub started on port {port}"
            )
            
        except Exception as e:
            logger.error(f"Failed to start JackTrip hub: {e}", exc_info=True)
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message=str(e)
            )
    
    def StopHub(self, request, context):
        """Stop JackTrip hub."""
        if not self.hub_process or self.hub_process.poll() is not None:
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message="Hub not running"
            )
        
        try:
            # Send SIGTERM to process group
            os.killpg(os.getpgid(self.hub_process.pid), signal.SIGTERM)
            
            # Wait for termination
            self.hub_process.wait(timeout=5)
            self.hub_process = None
            self.hub_config = {}
            
            return verdandi_pb2.JackTripOperationResponse(
                success=True,
                message="JackTrip hub stopped"
            )
            
        except Exception as e:
            logger.error(f"Failed to stop JackTrip hub: {e}", exc_info=True)
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message=str(e)
            )
    
    def StartClient(self, request, context):
        """Start JackTrip in client mode."""
        if self.client_process and self.client_process.poll() is None:
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message="Client already running"
            )
        
        try:
            hub_address = request.hub_address
            hub_port = request.hub_port or 4464
            send_channels = request.send_channels or 2
            receive_channels = request.receive_channels or 2
            buffer_size = request.buffer_size or 128
            
            # Use local hostname as client name so hub sees our node name
            import socket
            hostname = socket.gethostname().split('.')[0]  # Remove domain if present
            
            # Resolve hub address to hostname
            try:
                hub_hostname = socket.gethostbyaddr(hub_address)[0].split('.')[0]
            except:
                # Fallback to address if can't resolve
                hub_hostname = hub_address.split('.')[0] if '.' in hub_address else hub_address
            
            # Build JackTrip command for client mode
            cmd = [
                "jacktrip",
                "-C", hub_hostname,  # Use hostname not IP
            ]
            
            # Add peer port if not default
            if hub_port != 4464:
                cmd.extend(["--peerport", str(hub_port)])
            
            # Add channel specs
            cmd.extend([
                "-n", str(send_channels),
                "-o", str(receive_channels)
            ])
            # Note: Removed --clientname and --remotename as they may cause naming issues
            
            logger.info(f"Starting JackTrip client: {' '.join(cmd)}")
            
            # Start process
            self.client_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            
            # Store config
            self.client_config = {
                "hub_address": hub_address,
                "hub_port": hub_port,
                "send_channels": send_channels,
                "receive_channels": receive_channels,
                "buffer_size": buffer_size
            }
            
            return verdandi_pb2.JackTripOperationResponse(
                success=True,
                message=f"JackTrip client connected to {hub_address}:{hub_port}"
            )
            
        except Exception as e:
            logger.error(f"Failed to start JackTrip client: {e}", exc_info=True)
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message=str(e)
            )
    
    def StopClient(self, request, context):
        """Stop JackTrip client."""
        if not self.client_process or self.client_process.poll() is not None:
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message="Client not running"
            )
        
        try:
            # Send SIGTERM to process group
            os.killpg(os.getpgid(self.client_process.pid), signal.SIGTERM)
            
            # Wait for termination
            self.client_process.wait(timeout=5)
            self.client_process = None
            self.client_config = {}
            
            return verdandi_pb2.JackTripOperationResponse(
                success=True,
                message="JackTrip client stopped"
            )
            
        except Exception as e:
            logger.error(f"Failed to stop JackTrip client: {e}", exc_info=True)
            return verdandi_pb2.JackTripOperationResponse(
                success=False,
                message=str(e)
            )
    
    def GetJackTripStatus(self, request, context):
        """Get current JackTrip status."""
        hub_running = self.hub_process and self.hub_process.poll() is None
        client_running = self.client_process and self.client_process.poll() is None
        
        return verdandi_pb2.JackTripStatusResponse(
            hub_running=hub_running,
            client_running=client_running,
            hub_address=self.client_config.get("hub_address", ""),
            hub_port=self.client_config.get("hub_port", 0),
            connected_clients=[]  # TODO: Parse jacktrip output for connected clients
        )
