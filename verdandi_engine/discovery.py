"""
mDNS/Avahi service discovery for Verdandi nodes.
"""

import asyncio
import socket
import structlog
from typing import Dict, Optional, Callable
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf, ServiceStateChange
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser

from verdandi_codex.config import VerdandiConfig


logger = structlog.get_logger()


class DiscoveryService:
    """
    Manages mDNS advertisement and discovery of Verdandi nodes.
    """
    
    SERVICE_TYPE = "_verdandi._tcp.local."
    
    def __init__(self, config: VerdandiConfig):
        self.config = config
        self.aiozc: Optional[AsyncZeroconf] = None
        self.browser: Optional[AsyncServiceBrowser] = None
        self.discovered_nodes: Dict[str, ServiceInfo] = {}
        self.callbacks: list[Callable] = []
    
    async def start(self):
        """Start advertising and discovery."""
        logger.info("starting_mdns_discovery")
        
        self.aiozc = AsyncZeroconf()
        
        # Register our service
        if self.config.daemon.enable_mdns:
            await self._register_service()
        
        # Start browsing for other nodes
        self.browser = AsyncServiceBrowser(
            self.aiozc.zeroconf,
            self.SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )
        
        logger.info("mdns_discovery_started")
    
    async def stop(self):
        """Stop advertising and discovery."""
        logger.info("stopping_mdns_discovery")
        
        if self.aiozc:
            await self.aiozc.async_close()
        
        logger.info("mdns_discovery_stopped")
    
    async def _register_service(self):
        """Register this node's service with mDNS."""
        # Get local IP address
        local_ip = self._get_local_ip()
        
        # Get certificate fingerprint
        from verdandi_codex.crypto import NodeCertificateManager
        cert_manager = NodeCertificateManager()
        fingerprint = cert_manager.get_certificate_fingerprint() or ""
        
        # Create service info
        # Use node_id prefix for unique service name
        service_name = f"{self.config.node.node_id[:8]}-{self.config.node.hostname}.{self.SERVICE_TYPE}"
        
        info = ServiceInfo(
            self.SERVICE_TYPE,
            service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self.config.daemon.grpc_port,
            properties={
                "node_id": self.config.node.node_id,
                "hostname": self.config.node.hostname,
                "display_name": self.config.node.display_name or "",
                "version": "0.1.0",
                "cert_fingerprint": fingerprint,
            },
            server=f"{self.config.node.hostname}.local.",
        )
        
        await self.aiozc.async_register_service(info)
        
        logger.info(
            "mdns_service_registered",
            hostname=self.config.node.hostname,
            ip=local_ip,
            port=self.config.daemon.grpc_port,
        )
    
    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ):
        """Handle service state changes."""
        if state_change is ServiceStateChange.Added:
            asyncio.create_task(self._on_service_added(zeroconf, service_type, name))
        elif state_change is ServiceStateChange.Removed:
            self._on_service_removed(name)
        elif state_change is ServiceStateChange.Updated:
            asyncio.create_task(self._on_service_updated(zeroconf, service_type, name))
    
    async def _on_service_added(self, zeroconf: Zeroconf, service_type: str, name: str):
        """Handle new service discovered."""
        info = await asyncio.get_event_loop().run_in_executor(
            None, zeroconf.get_service_info, service_type, name
        )
        
        if info:
            # Don't add ourselves
            node_id = info.properties.get(b"node_id", b"").decode("utf-8")
            if node_id == self.config.node.node_id:
                return
            
            self.discovered_nodes[name] = info
            
            hostname = info.properties.get(b"hostname", b"").decode("utf-8")
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            
            logger.info(
                "node_discovered",
                node_id=node_id,
                hostname=hostname,
                addresses=addresses,
                port=info.port,
            )
            
            # Notify callbacks
            for callback in self.callbacks:
                try:
                    await callback("discovered", info)
                except Exception as e:
                    logger.error("callback_error", error=str(e))
    
    def _on_service_removed(self, name: str):
        """Handle service removed."""
        if name in self.discovered_nodes:
            info = self.discovered_nodes.pop(name)
            node_id = info.properties.get(b"node_id", b"").decode("utf-8")
            hostname = info.properties.get(b"hostname", b"").decode("utf-8")
            
            logger.info(
                "node_lost",
                node_id=node_id,
                hostname=hostname,
            )
            
            # Notify callbacks
            for callback in self.callbacks:
                try:
                    asyncio.create_task(callback("lost", info))
                except Exception as e:
                    logger.error("callback_error", error=str(e))
    
    async def _on_service_updated(self, zeroconf: Zeroconf, service_type: str, name: str):
        """Handle service updated."""
        info = await asyncio.get_event_loop().run_in_executor(
            None, zeroconf.get_service_info, service_type, name
        )
        
        if info and name in self.discovered_nodes:
            self.discovered_nodes[name] = info
            
            node_id = info.properties.get(b"node_id", b"").decode("utf-8")
            hostname = info.properties.get(b"hostname", b"").decode("utf-8")
            
            logger.debug(
                "node_updated",
                node_id=node_id,
                hostname=hostname,
            )
            
            # Notify callbacks
            for callback in self.callbacks:
                try:
                    await callback("updated", info)
                except Exception as e:
                    logger.error("callback_error", error=str(e))
    
    def register_callback(self, callback: Callable):
        """Register a callback for discovery events."""
        self.callbacks.append(callback)
    
    def get_discovered_nodes(self) -> Dict[str, ServiceInfo]:
        """Get all currently discovered nodes."""
        return self.discovered_nodes.copy()
    
    def _get_local_ip(self) -> str:
        """Get the local IP address."""
        try:
            # Connect to a public DNS server to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"
