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
from .fabric_manager import FabricGraphManager
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


class FabricGraphServicer(verdandi_pb2_grpc.FabricGraphServiceServicer):
    """Implementation of FabricGraphService."""
    
    def __init__(
        self, 
        config: VerdandiConfig, 
        fabric_manager: FabricGraphManager,
        jacktrip_manager,
        rtpmidi_manager,
        jack_connection_manager
    ):
        self.config = config
        self.fabric_manager = fabric_manager
        self.jacktrip_manager = jacktrip_manager
        self.rtpmidi_manager = rtpmidi_manager
        self.jack_connection_manager = jack_connection_manager
    
    def GetFabricGraph(self, request, context):
        """Return current fabric graph state."""
        try:
            graph = self.fabric_manager.get_graph(request.graph_id or None)
            
            if not graph:
                context.abort(grpc.StatusCode.NOT_FOUND, "Graph not found")
            
            # Get all links for this graph
            links = self.fabric_manager.list_links(str(graph.graph_id))
            
            link_infos = []
            for link in links:
                bundles = [
                    verdandi_pb2.BundleInfo(
                        bundle_id=str(bundle.bundle_id),
                        name=bundle.name,
                        directionality=bundle.directionality.value,
                        channels=bundle.channels,
                        format=bundle.format,
                    )
                    for bundle in link.bundles
                ]
                
                link_infos.append(
                    verdandi_pb2.FabricLinkInfo(
                        link_id=str(link.link_id),
                        link_type=link.link_type.value,
                        node_a_id=str(link.node_a_id),
                        node_b_id=str(link.node_b_id),
                        status=link.status.value,
                        params_json=json.dumps(link.params_json),
                        bundles=bundles,
                        created_at=int(link.created_at.timestamp() * 1000),
                    )
                )
            
            return verdandi_pb2.FabricGraphResponse(
                graph_id=str(graph.graph_id),
                name=graph.name,
                version=graph.version,
                links=link_infos,
                updated_at=int(graph.updated_at.timestamp() * 1000),
            )
            
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))
    
    def CreateAudioLink(self, request, context):
        """Create an audio link between two nodes."""
        try:
            params = json.loads(request.params_json) if request.params_json else None
            
            link = self.fabric_manager.create_audio_link(
                node_a_id=request.node_a_id,
                node_b_id=request.node_b_id,
                params=params,
                create_voice_bundle=request.create_voice_cmd_bundle,
            )
            
            # Start JackTrip session if this is the local node
            if self.jacktrip_manager and request.node_a_id == self.config.node.node_id:
                # Extract connection params
                remote_host = params.get("remote_host") if params else None
                remote_port = params.get("remote_port", 4464) if params else 4464
                channels = params.get("channels", 2) if params else 2
                
                if remote_host:
                    import asyncio
                    import threading
                    
                    # Run async code in a new thread with its own event loop
                    def start_session():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            success = loop.run_until_complete(
                                self.jacktrip_manager.create_audio_link(
                                    link_id=str(link.link_id),
                                    remote_host=remote_host,
                                    remote_port=remote_port,
                                    channels=channels
                                )
                            )
                            
                            if success:
                                # Auto-connect JACK ports
                                loop.run_until_complete(
                                    self.jack_connection_manager.connect_link_ports(str(link.link_id))
                                )
                        finally:
                            loop.close()
                    
                    thread = threading.Thread(target=start_session, daemon=True)
                    thread.start()
                    thread.join(timeout=2.0)  # Wait up to 2 seconds
            
            return verdandi_pb2.LinkOperationResponse(
                success=True,
                message=f"Audio link created between {request.node_a_id[:8]} and {request.node_b_id[:8]}",
                link_id=str(link.link_id),
            )
            
        except Exception as e:
            return verdandi_pb2.LinkOperationResponse(
                success=False,
                message=f"Failed to create audio link: {str(e)}",
                link_id="",
            )
    
    def CreateMidiLink(self, request, context):
        """Create a MIDI link between two nodes."""
        try:
            params = json.loads(request.params_json) if request.params_json else None
            
            link = self.fabric_manager.create_midi_link(
                node_a_id=request.node_a_id,
                node_b_id=request.node_b_id,
                params=params,
            )
            
            # Start RTP-MIDI session if this is the local node
            if self.rtpmidi_manager and request.node_a_id == self.config.node.node_id:
                # Extract connection params
                remote_host = params.get("remote_host") if params else None
                remote_port = params.get("remote_port", 5004) if params else 5004
                
                if remote_host:
                    import asyncio
                    import threading
                    
                    def start_session():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                self.rtpmidi_manager.create_midi_link(
                                    link_id=str(link.link_id),
                                    remote_host=remote_host,
                                    remote_port=remote_port
                                )
                            )
                        finally:
                            loop.close()
                    
                    thread = threading.Thread(target=start_session, daemon=True)
                    thread.start()
                    thread.join(timeout=2.0)
            
            return verdandi_pb2.LinkOperationResponse(
                success=True,
                message=f"MIDI link created between {request.node_a_id[:8]} and {request.node_b_id[:8]}",
                link_id=str(link.link_id),
            )
            
        except Exception as e:
            return verdandi_pb2.LinkOperationResponse(
                success=False,
                message=f"Failed to create MIDI link: {str(e)}",
                link_id="",
            )
    
    def RemoveLink(self, request, context):
        """Remove a link from the fabric graph."""
        try:
            # Get link info before removing
            link = self.fabric_manager.get_link(request.link_id)
            
            # Stop session managers for this link
            if link:
                import asyncio
                import threading
                
                def stop_session():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        if link.link_type.value == "audio" and self.jacktrip_manager:
                            loop.run_until_complete(
                                self.jack_connection_manager.disconnect_link_ports(request.link_id)
                            )
                            loop.run_until_complete(
                                self.jacktrip_manager.remove_audio_link(request.link_id)
                            )
                        elif link.link_type.value == "midi" and self.rtpmidi_manager:
                            loop.run_until_complete(
                                self.rtpmidi_manager.remove_midi_link(request.link_id)
                            )
                    finally:
                        loop.close()
                
                thread = threading.Thread(target=stop_session, daemon=True)
                thread.start()
                thread.join(timeout=2.0)
            
            success = self.fabric_manager.remove_link(request.link_id)
            
            if success:
                return verdandi_pb2.LinkOperationResponse(
                    success=True,
                    message="Link removed successfully",
                    link_id=request.link_id,
                )
            else:
                return verdandi_pb2.LinkOperationResponse(
                    success=False,
                    message="Link not found",
                    link_id=request.link_id,
                )
                
        except Exception as e:
            return verdandi_pb2.LinkOperationResponse(
                success=False,
                message=f"Failed to remove link: {str(e)}",
                link_id=request.link_id,
            )
    
    def GetLinkStatus(self, request, context):
        """Get status of a specific link."""
        try:
            link = self.fabric_manager.get_link(request.link_id)
            
            if not link:
                context.abort(grpc.StatusCode.NOT_FOUND, "Link not found")
            
            # Check actual session status
            observed_status = "UNKNOWN"
            error_message = ""
            
            import asyncio
            import threading
            
            status_result = {"is_active": False, "message": ""}
            
            def check_status():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if link.link_type.value == "audio" and self.jacktrip_manager:
                        is_active, status_msg = loop.run_until_complete(
                            self.jacktrip_manager.get_link_status(request.link_id)
                        )
                        status_result["is_active"] = is_active
                        status_result["message"] = status_msg or ""
                    elif link.link_type.value == "midi" and self.rtpmidi_manager:
                        is_active, status_msg = loop.run_until_complete(
                            self.rtpmidi_manager.get_link_status(request.link_id)
                        )
                        status_result["is_active"] = is_active
                        status_result["message"] = status_msg or ""
                finally:
                    loop.close()
            
            thread = threading.Thread(target=check_status, daemon=True)
            thread.start()
            thread.join(timeout=1.0)
            
            observed_status = "ACTIVE" if status_result["is_active"] else "INACTIVE"
            if not status_result["is_active"]:
                error_message = status_result["message"]
            
            return verdandi_pb2.LinkStatusResponse(
                link_id=str(link.link_id),
                status=link.status.value,
                observed_status=observed_status,
                error_message=error_message,
            )
            
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))
    
    def ListLinks(self, request, context):
        """List all links in the fabric graph."""
        try:
            links = self.fabric_manager.list_links()
            
            link_infos = []
            for link in links:
                bundles = [
                    verdandi_pb2.BundleInfo(
                        bundle_id=str(bundle.bundle_id),
                        name=bundle.name,
                        directionality=bundle.directionality.value,
                        channels=bundle.channels,
                        format=bundle.format,
                    )
                    for bundle in link.bundles
                ]
                
                link_infos.append(
                    verdandi_pb2.FabricLinkInfo(
                        link_id=str(link.link_id),
                        link_type=link.link_type.value,
                        node_a_id=str(link.node_a_id),
                        node_b_id=str(link.node_b_id),
                        status=link.status.value,
                        params_json=json.dumps(link.params_json),
                        bundles=bundles,
                        created_at=int(link.created_at.timestamp() * 1000),
                    )
                )
            
            return verdandi_pb2.ListLinksResponse(links=link_infos)
            
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))

