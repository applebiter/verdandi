"""
gRPC service implementations for Verdandi Engine.
"""

import grpc
import platform
import psutil
import time
import json
from datetime import datetime
from typing import Optional

from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc
from verdandi_codex.config import VerdandiConfig
from .node_registry import NodeRegistry


class NodeIdentityServicer(verdandi_pb2_grpc.NodeIdentityServiceServicer):
    """Implementation of NodeIdentityService."""
    
    def __init__(self, config: VerdandiConfig):
        self.config = config
        self.daemon_version = "0.1.0"
    
    def GetNodeInfo(self, request, context):
        """Return node identity information."""
        from verdandi_codex.crypto import NodeCertificateManager
        
        cert_manager = NodeCertificateManager()
        fingerprint = cert_manager.get_certificate_fingerprint() or ""
        
        return verdandi_pb2.NodeInfo(
            node_id=self.config.node.node_id,
            hostname=self.config.node.hostname,
            display_name=self.config.node.display_name or "",
            daemon_version=self.daemon_version,
            cert_fingerprint=fingerprint,
        )
    
    def Ping(self, request, context):
        """Handle ping request."""
        server_time = int(time.time() * 1000)  # milliseconds
        return verdandi_pb2.PingResponse(
            timestamp=request.timestamp,
            server_timestamp=server_time,
        )


class HealthMetricsServicer(verdandi_pb2_grpc.HealthMetricsServiceServicer):
    """Implementation of HealthMetricsService."""
    
    def __init__(self, config: VerdandiConfig):
        self.config = config
        self.start_time = time.time()
    
    def GetHealthSnapshot(self, request, context):
        """Return current health metrics."""
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        # GPU metrics would require nvidia-smi or similar
        gpu_percent = 0.0
        vram_free_mb = 0
        
        uptime = int(time.time() - self.start_time)
        
        return verdandi_pb2.HealthSnapshot(
            cpu_usage_percent=cpu_percent,
            ram_usage_percent=memory.percent,
            gpu_usage_percent=gpu_percent,
            vram_free_mb=vram_free_mb,
            daemon_uptime_seconds=uptime,
            degraded_mode=False,
            status="healthy",
        )
    
    def WatchHealth(self, request, context):
        """Stream health updates."""
        interval = request.interval_seconds or 5
        
        while context.is_active():
            snapshot = self.GetHealthSnapshot(None, context)
            yield verdandi_pb2.HealthEvent(
                timestamp=int(time.time() * 1000),
                snapshot=snapshot,
            )
            time.sleep(interval)


class DiscoveryAndRegistryServicer(verdandi_pb2_grpc.DiscoveryAndRegistryServiceServicer):
    """Implementation of DiscoveryAndRegistryService."""
    
    def __init__(self, config: VerdandiConfig, node_registry: Optional[NodeRegistry] = None):
        self.config = config
        self.known_nodes = {}  # Will be populated by discovery
        self.node_registry = node_registry
    
    def GetKnownNodes(self, request, context):
        """Return list of known nodes."""
        nodes = []
        for node_data in self.known_nodes.values():
            nodes.append(node_data)
        
        return verdandi_pb2.KnownNodesResponse(nodes=nodes)
    
    def WatchPresence(self, request, context):
        """Stream node presence changes."""
        # Placeholder - will integrate with mDNS discovery
        while context.is_active():
            time.sleep(1)
