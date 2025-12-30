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


logger = structlog.get_logger()


class VerdandiDaemon:
    """Main daemon class for Verdandi Engine."""
    
    def __init__(self, config: VerdandiConfig):
        self.config = config
        self.running = False
        self.db: Database = None
        self.grpc_server: GrpcServer = None
        
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
        except Exception as e:
            logger.error("database_connection_failed", error=str(e))
            # Continue in degraded mode
            self.db = None
        
        # Start gRPC server
        self.grpc_server = GrpcServer(self.config)
        self.grpc_server.start()
        
        self.running = True
        logger.info("verdandi_engine_started")
        
        # Main loop
        while self.running:
            await asyncio.sleep(1)
    
    async def stop(self):
        """Stop the daemon gracefully."""
        logger.info("stopping_verdandi_engine")
        self.running = False
        
        # Stop gRPC server
        if self.grpc_server:
            self.grpc_server.stop()
        
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
