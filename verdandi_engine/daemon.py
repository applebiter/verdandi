"""
Verdandi Engine - Main daemon entry point.
"""

import sys
import signal
import asyncio
import structlog
from pathlib import Path

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.crypto import NodeCertificateManager
from .grpc_server import GrpcServer
from .discovery import DiscoveryService
from .fabric_manager import FabricGraphManager
from .node_registry import NodeRegistry
from .jacktrip_manager import JackTripManager
from .rtpmidi_manager import RTPMidiManager
from .jack_connection_manager import JackConnectionManager


logger = structlog.get_logger()


class VerdandiDaemon:
    """Main daemon class for Verdandi Engine."""
    
    def __init__(self, config: VerdandiConfig):
        self.config = config
        self.running = False
        self.db: Database = None
        self.grpc_server: GrpcServer = None
        self.discovery: DiscoveryService = None
        self.fabric_manager: FabricGraphManager = None
        self.node_registry: NodeRegistry = None
        self.jacktrip_manager: JackTripManager = None
        self.rtpmidi_manager: RTPMidiManager = None
        self.jack_connection_manager: JackConnectionManager = None
        
    async def start(self):
        """Start the daemon."""
        logger.info(
            "starting_verdandi_engine",
            node_id=self.config.node.node_id,
            hostname=self.config.node.hostname,
        )
        
        # Ensure certificates exist
        logger.info("ensuring_certificates")
        cert_manager = NodeCertificateManager()
        created = cert_manager.ensure_node_certificate(
            self.config.node.node_id,
            self.config.node.hostname,
        )
        if created:
            logger.info("certificates_created")
        else:
            logger.info("certificates_exist")
        
        # Initialize database connection
        try:
            self.db = Database(self.config.database)
            logger.info("database_connected", host=self.config.database.host)
            
            # Initialize managers that require database
            self.fabric_manager = FabricGraphManager(self.db, self.config)
            self.node_registry = NodeRegistry(self.db, self.config)
            self.jacktrip_manager = JackTripManager(self.config, self.db)
            self.rtpmidi_manager = RTPMidiManager(self.config, self.db)
            self.jack_connection_manager = JackConnectionManager(self.config, self.db)
            
            # Initialize session managers
            await self.jacktrip_manager.initialize()
            await self.rtpmidi_manager.initialize()
            await self.jack_connection_manager.initialize()
            
            # Ensure default fabric graph exists
            self.fabric_manager.ensure_default_graph()
            
        except Exception as e:
            logger.error("database_connection_failed", error=str(e))
            # Continue in degraded mode
            self.db = None
        
            # Register callback to persist discovered nodes
            if self.node_registry:
                async def on_discovery_event(event_type, service_info):
                    if event_type == "discovered":
                        self.node_registry.register_from_mdns(service_info)
                
                self.discovery.register_callback(on_discovery_event)
            
            
        # Start gRPC server
        self.grpc_server = GrpcServer(
            self.config, 
            self.fabric_manager, 
            self.node_registry,
            self.jacktrip_manager if self.db else None,
            self.rtpmidi_manager if self.db else None,
            self.jack_connection_manager if self.db else None
        )
        self.grpc_server.start()
        
        # Start mDNS discovery
        if self.config.daemon.enable_mdns:
            self.discovery = DiscoveryService(self.config)
            await self.discovery.start()
        
        self.running = True
        logger.info("verdandi_engine_started")
        
        # Main loop
        while self.running:
            await asyncio.sleep(1)
    
    async def stop(self):
        """Stop the daemon gracefully."""
        logger.info("stopping_verdandi_engine")
        self.running = False
        
        # Stop discovery
        if self.discovery:
            await self.discovery.stop()
        
        # Stop gRPC server
        if self.grpc_server:
            self.grpc_server.stop()
        
        # Shutdown session managers
        if self.jack_connection_manager:
            await self.jack_connection_manager.shutdown()
            
        if self.jacktrip_manager:
            await self.jacktrip_manager.shutdown()
            
        if self.rtpmidi_manager:
            await self.rtpmidi_manager.shutdown()
        
        # Cleanup database
        if self.db:
            pass
        
        logger.info("verdandi_engine_stopped")


async def async_main():
    """Async main function."""
    # Load configuration
    config = VerdandiConfig.load()
    
    # Create daemon
    daemon = VerdandiDaemon(config)
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler(signum, frame):
        logger.info("received_signal", signal=signum)
        asyncio.create_task(daemon.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start daemon
    try:
        await daemon.start()
    except Exception as e:
        logger.error("daemon_error", error=str(e), exc_info=True)
        return 1
    
    return 0


def main():
    """Main entry point for verdandi-engine."""
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    
    # Run async main
    try:
        exit_code = asyncio.run(async_main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        sys.exit(0)


if __name__ == "__main__":
    main()
