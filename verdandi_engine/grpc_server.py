"""
gRPC server for Verdandi Engine daemon.
"""

import grpc
from concurrent import futures
import structlog
from pathlib import Path
from typing import Optional

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.proto import verdandi_pb2_grpc
from .services import (
    NodeIdentityServicer,
    HealthMetricsServicer,
    DiscoveryAndRegistryServicer,
    FabricGraphServicer,
)
from .jack_service import JackServicer
from .jacktrip_service import JackTripServicer
from .fabric_manager import FabricGraphManager
from .node_registry import NodeRegistry


logger = structlog.get_logger()


class GrpcServer:
    """gRPC server manager for daemon services."""
    
    def __init__(
        self,
        config: VerdandiConfig,
        fabric_manager: FabricGraphManager,
        node_registry: NodeRegistry,
        jacktrip_manager=None,
        rtpmidi_manager=None,
        jack_connection_manager=None
    ):
        self.config = config
        self.fabric_manager = fabric_manager
        self.node_registry = node_registry
        self.jacktrip_manager = jacktrip_manager
        self.rtpmidi_manager = rtpmidi_manager
        self.jack_connection_manager = jack_connection_manager
        self.server: Optional[grpc.Server] = None
    
    def start(self):
        """Start the gRPC server."""
        self.server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10),
            options=[
                ("grpc.max_send_message_length", 50 * 1024 * 1024),
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
            ],
        )
        
        # Register services
        verdandi_pb2_grpc.add_NodeIdentityServiceServicer_to_server(
            NodeIdentityServicer(self.config), self.server
        )
        verdandi_pb2_grpc.add_HealthMetricsServiceServicer_to_server(
            HealthMetricsServicer(self.config), self.server
        )
        verdandi_pb2_grpc.add_DiscoveryAndRegistryServiceServicer_to_server(
            DiscoveryAndRegistryServicer(self.config, self.node_registry), self.server
        )
        verdandi_pb2_grpc.add_FabricGraphServiceServicer_to_server(
            FabricGraphServicer(
                self.config, 
                self.fabric_manager,
                self.jacktrip_manager,
                self.rtpmidi_manager,
                self.jack_connection_manager
            ), 
            self.server
        )
        verdandi_pb2_grpc.add_JackServiceServicer_to_server(
            JackServicer(self.jack_connection_manager), self.server
        )
        verdandi_pb2_grpc.add_JackTripServiceServicer_to_server(
            JackTripServicer(), self.server
        )
        
        # Configure TLS if enabled
        if self.config.daemon.tls_enabled:
            server_credentials = self._load_tls_credentials()
            if server_credentials:
                self.server.add_secure_port(
                    f"{self.config.daemon.grpc_host}:{self.config.daemon.grpc_port}",
                    server_credentials,
                )
                logger.info(
                    "grpc_server_starting_secure",
                    host=self.config.daemon.grpc_host,
                    port=self.config.daemon.grpc_port,
                )
            else:
                logger.warning("tls_credentials_not_found_using_insecure")
                self.server.add_insecure_port(
                    f"{self.config.daemon.grpc_host}:{self.config.daemon.grpc_port}"
                )
        else:
            self.server.add_insecure_port(
                f"{self.config.daemon.grpc_host}:{self.config.daemon.grpc_port}"
            )
            logger.info(
                "grpc_server_starting_insecure",
                host=self.config.daemon.grpc_host,
                port=self.config.daemon.grpc_port,
            )
        
        self.server.start()
        logger.info("grpc_server_started")
    
    def _load_tls_credentials(self) -> Optional[grpc.ServerCredentials]:
        """Load TLS credentials for secure connections."""
        from verdandi_codex.crypto import NodeCertificateManager
        
        cert_manager = NodeCertificateManager()
        
        # Ensure certificates exist
        cert_manager.ensure_node_certificate(
            self.config.node.node_id,
            self.config.node.hostname,
        )
        
        paths = cert_manager.get_certificate_paths()
        
        try:
            with open(paths["ca_cert"], "rb") as f:
                ca_cert = f.read()
            with open(paths["node_cert"], "rb") as f:
                node_cert = f.read()
            with open(paths["node_key"], "rb") as f:
                node_key = f.read()
            
            # Create server credentials with mutual TLS
            server_credentials = grpc.ssl_server_credentials(
                [(node_key, node_cert)],
                root_certificates=ca_cert,
                require_client_auth=True,
            )
            
            return server_credentials
        except Exception as e:
            logger.error("failed_to_load_tls_credentials", error=str(e))
            return None
    
    def stop(self, grace_period: int = 5):
        """Stop the gRPC server."""
        if self.server:
            logger.info("stopping_grpc_server", grace_period=grace_period)
            self.server.stop(grace_period)
            logger.info("grpc_server_stopped")
    
    def wait_for_termination(self):
        """Block until server terminates."""
        if self.server:
            self.server.wait_for_termination()
