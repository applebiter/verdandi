"""
Helper utilities for making gRPC calls to remote Verdandi nodes.
"""

import logging
import grpc
from typing import Optional

from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc
from verdandi_codex.database import Database
from verdandi_codex.models.identity import Node

logger = logging.getLogger(__name__)


class VerdandiGrpcClient:
    """Client for making gRPC calls to remote Verdandi nodes."""
    
    def __init__(self, node: Node, timeout: int = 10):
        """
        Initialize client for a specific node.
        
        Args:
            node: Node model with connection info
            timeout: Request timeout in seconds
        """
        self.node = node
        self.timeout = timeout
        self.address = f"{node.ip_last_seen}:{node.daemon_port}"
        
        # Create channel (insecure for now, TODO: add TLS)
        self.channel = grpc.insecure_channel(
            self.address,
            options=[
                ("grpc.max_send_message_length", 50 * 1024 * 1024),
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
            ]
        )
        
        # Create stubs
        self.identity_stub = verdandi_pb2_grpc.NodeIdentityServiceStub(self.channel)
        self.jack_stub = verdandi_pb2_grpc.JackServiceStub(self.channel)
        self.jacktrip_stub = verdandi_pb2_grpc.JackTripServiceStub(self.channel)
    
    def close(self):
        """Close the gRPC channel."""
        if self.channel:
            self.channel.close()
    
    def get_jack_graph(self):
        """Fetch JACK graph from remote node."""
        try:
            response = self.jack_stub.GetJackGraph(
                verdandi_pb2.Empty(),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to get JACK graph from {self.node.hostname}: {e}")
            raise
    
    def connect_jack_ports(self, output_port: str, input_port: str):
        """Connect two JACK ports on remote node."""
        try:
            response = self.jack_stub.ConnectPorts(
                verdandi_pb2.ConnectPortsRequest(
                    output_port=output_port,
                    input_port=input_port
                ),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to connect ports on {self.node.hostname}: {e}")
            raise
    
    def disconnect_jack_ports(self, output_port: str, input_port: str):
        """Disconnect two JACK ports on remote node."""
        try:
            response = self.jack_stub.DisconnectPorts(
                verdandi_pb2.DisconnectPortsRequest(
                    output_port=output_port,
                    input_port=input_port
                ),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to disconnect ports on {self.node.hostname}: {e}")
            raise
    
    def start_jacktrip_hub(self, send_channels: int, receive_channels: int, 
                           sample_rate: int = 48000, buffer_size: int = 128, port: int = 4464):
        """Start JackTrip hub on remote node."""
        try:
            response = self.jacktrip_stub.StartHub(
                verdandi_pb2.StartHubRequest(
                    send_channels=send_channels,
                    receive_channels=receive_channels,
                    sample_rate=sample_rate,
                    buffer_size=buffer_size,
                    port=port
                ),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to start JackTrip hub on {self.node.hostname}: {e}")
            raise
    
    def stop_jacktrip_hub(self):
        """Stop JackTrip hub on remote node."""
        try:
            response = self.jacktrip_stub.StopHub(
                verdandi_pb2.StopHubRequest(),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to stop JackTrip hub on {self.node.hostname}: {e}")
            raise
    
    def start_jacktrip_client(self, hub_address: str, hub_port: int,
                              send_channels: int, receive_channels: int,
                              sample_rate: int = 48000, buffer_size: int = 128):
        """Start JackTrip client on remote node."""
        try:
            response = self.jacktrip_stub.StartClient(
                verdandi_pb2.StartClientRequest(
                    hub_address=hub_address,
                    hub_port=hub_port,
                    send_channels=send_channels,
                    receive_channels=receive_channels,
                    sample_rate=sample_rate,
                    buffer_size=buffer_size
                ),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to start JackTrip client on {self.node.hostname}: {e}")
            raise
    
    def stop_jacktrip_client(self):
        """Stop JackTrip client on remote node."""
        try:
            response = self.jacktrip_stub.StopClient(
                verdandi_pb2.StopClientRequest(),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to stop JackTrip client on {self.node.hostname}: {e}")
            raise
    
    def get_jacktrip_status(self):
        """Get JackTrip status from remote node."""
        try:
            response = self.jacktrip_stub.GetJackTripStatus(
                verdandi_pb2.Empty(),
                timeout=self.timeout
            )
            return response
        except grpc.RpcError as e:
            logger.error(f"Failed to get JackTrip status from {self.node.hostname}: {e}")
            raise
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def get_grpc_client(node_id: str, database: Database) -> Optional[VerdandiGrpcClient]:
    """
    Helper to get a gRPC client for a node by ID.
    
    Args:
        node_id: Node ID to connect to
        database: Database instance
        
    Returns:
        VerdandiGrpcClient or None if node not found
    """
    try:
        with database.get_session() as session:
            node = session.query(Node).filter_by(node_id=node_id).first()
            if not node:
                logger.error(f"Node {node_id} not found in database")
                return None
            
            # Detach from session before returning
            session.expunge(node)
            return VerdandiGrpcClient(node)
    except Exception as e:
        logger.error(f"Failed to create gRPC client: {e}", exc_info=True)
        return None
