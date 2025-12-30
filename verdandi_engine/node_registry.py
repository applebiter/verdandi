"""
Node registry manager - persists discovered nodes to database.
"""

import structlog
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional
from zeroconf import ServiceInfo
import socket

from verdandi_codex.database import Database
from verdandi_codex.models import Node, NodeCapability, ServiceEndpoint
from verdandi_codex.config import VerdandiConfig


logger = structlog.get_logger()


class NodeRegistry:
    """Manages node registration and capability tracking in the database."""
    
    def __init__(self, db: Database, config: VerdandiConfig):
        self.db = db
        self.config = config
    
    def register_or_update_node(
        self,
        node_id: str,
        hostname: str,
        ip_address: str,
        daemon_port: int,
        display_name: Optional[str] = None,
        cert_fingerprint: Optional[str] = None,
    ) -> Node:
        """Register a new node or update existing node information."""
        session = self.db.get_session()
        
        try:
            # Check if node exists
            node = session.query(Node).filter_by(node_id=node_id).first()
            
            if node:
                # Update existing node
                node.hostname = hostname
                node.ip_last_seen = ip_address
                node.daemon_port = daemon_port
                node.last_seen_at = datetime.utcnow()
                node.status = "online"
                
                if display_name:
                    node.display_name = display_name
                if cert_fingerprint:
                    node.cert_fingerprint = cert_fingerprint
                
                logger.debug("node_updated", node_id=node_id, hostname=hostname)
            else:
                # Create new node
                node = Node(
                    node_id=node_id,
                    hostname=hostname,
                    display_name=display_name or hostname,
                    ip_last_seen=ip_address,
                    daemon_port=daemon_port,
                    cert_fingerprint=cert_fingerprint,
                    status="online",
                )
                session.add(node)
                
                logger.info("node_registered", node_id=node_id, hostname=hostname)
            
            session.commit()
            return node
            
        except Exception as e:
            session.rollback()
            logger.error("node_registration_failed", error=str(e), node_id=node_id)
            raise
        finally:
            session.close()
    
    def register_from_mdns(self, service_info: ServiceInfo):
        """Register a node from mDNS ServiceInfo."""
        try:
            # Extract properties safely
            node_id_bytes = service_info.properties.get(b"node_id")
            hostname_bytes = service_info.properties.get(b"hostname")
            display_name_bytes = service_info.properties.get(b"display_name")
            cert_fingerprint_bytes = service_info.properties.get(b"cert_fingerprint")
            
            node_id = node_id_bytes.decode("utf-8") if node_id_bytes else ""
            hostname = hostname_bytes.decode("utf-8") if hostname_bytes else ""
            display_name = display_name_bytes.decode("utf-8") if display_name_bytes else ""
            cert_fingerprint = cert_fingerprint_bytes.decode("utf-8") if cert_fingerprint_bytes else ""
            
            if not node_id or not hostname:
                logger.warning("mdns_missing_required_fields", service=service_info.name)
                return
            
            # Get IP address
            if service_info.addresses:
                ip_address = socket.inet_ntoa(service_info.addresses[0])
            else:
                logger.warning("mdns_no_address", service=service_info.name)
                return
            
            # Register node
            self.register_or_update_node(
                node_id=node_id,
                hostname=hostname,
                ip_address=ip_address,
                daemon_port=service_info.port,
                display_name=display_name or None,
                cert_fingerprint=cert_fingerprint or None,
            )
            
        except Exception as e:
            logger.error("mdns_registration_failed", error=str(e))
    
    def mark_node_offline(self, node_id: str):
        """Mark a node as offline."""
        session = self.db.get_session()
        
        try:
            node = session.query(Node).filter_by(node_id=node_id).first()
            if node:
                node.status = "offline"
                session.commit()
                logger.info("node_marked_offline", node_id=node_id)
        except Exception as e:
            session.rollback()
            logger.error("mark_offline_failed", error=str(e), node_id=node_id)
        finally:
            session.close()
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by ID."""
        session = self.db.get_session()
        try:
            return session.query(Node).filter_by(node_id=node_id).first()
        finally:
            session.close()
    
    def list_nodes(self, status: Optional[str] = None) -> list[Node]:
        """List all nodes, optionally filtered by status."""
        session = self.db.get_session()
        try:
            query = session.query(Node)
            if status:
                query = query.filter_by(status=status)
            return query.order_by(Node.hostname).all()
        finally:
            session.close()
    
    def update_capabilities(self, node_id: str, capabilities: dict):
        """Update node capabilities."""
        session = self.db.get_session()
        
        try:
            # Get or create capability record
            capability = session.query(NodeCapability).filter_by(node_id=node_id).first()
            
            if not capability:
                capability = NodeCapability(node_id=node_id)
                session.add(capability)
            
            # Update fields from dictionary
            for key, value in capabilities.items():
                if hasattr(capability, key):
                    setattr(capability, key, value)
            
            capability.updated_at = datetime.utcnow()
            session.commit()
            
            logger.debug("capabilities_updated", node_id=node_id)
            
        except Exception as e:
            session.rollback()
            logger.error("capability_update_failed", error=str(e), node_id=node_id)
        finally:
            session.close()
