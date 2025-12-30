"""
Fabric Graph manager - handles link creation, removal, and state management.
"""

import structlog
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid

from verdandi_codex.database import Database
from verdandi_codex.models import (
    FabricGraph,
    FabricLink,
    FabricBundle,
    LinkType,
    LinkStatus,
    Directionality,
)
from verdandi_codex.config import VerdandiConfig


logger = structlog.get_logger()


class FabricGraphManager:
    """Manages the fabric graph of audio and MIDI links between nodes."""
    
    def __init__(self, db: Database, config: VerdandiConfig):
        self.db = db
        self.config = config
    
    def ensure_default_graph(self) -> FabricGraph:
        """Ensure the default 'Home' fabric graph exists."""
        session = self.db.get_session()
        
        try:
            graph = session.query(FabricGraph).filter_by(name="Home").first()
            
            if not graph:
                graph = FabricGraph(name="Home", version=1)
                session.add(graph)
                session.commit()
                logger.info("default_graph_created")
            
            return graph
        finally:
            session.close()
    
    def get_graph(self, graph_id: Optional[str] = None) -> Optional[FabricGraph]:
        """Get fabric graph by ID or return default."""
        session = self.db.get_session()
        
        try:
            if graph_id:
                return session.query(FabricGraph).filter_by(graph_id=graph_id).first()
            else:
                # Return default "Home" graph
                return session.query(FabricGraph).filter_by(name="Home").first()
        finally:
            session.close()
    
    def create_audio_link(
        self,
        node_a_id: str,
        node_b_id: str,
        params: Optional[dict] = None,
        create_voice_bundle: bool = True,
    ) -> FabricLink:
        """Create an audio link between two nodes."""
        session = self.db.get_session()
        
        try:
            # Ensure graph exists
            graph = self.ensure_default_graph()
            
            # Check if link already exists
            existing = (
                session.query(FabricLink)
                .filter_by(
                    graph_id=graph.graph_id,
                    link_type=LinkType.AUDIO_JACKTRIP,
                )
                .filter(
                    ((FabricLink.node_a_id == node_a_id) & (FabricLink.node_b_id == node_b_id))
                    | ((FabricLink.node_a_id == node_b_id) & (FabricLink.node_b_id == node_a_id))
                )
                .first()
            )
            
            if existing:
                logger.warning(
                    "audio_link_exists",
                    link_id=existing.link_id,
                    node_a=node_a_id,
                    node_b=node_b_id,
                )
                return existing
            
            # Create link
            link = FabricLink(
                graph_id=graph.graph_id,
                link_type=LinkType.AUDIO_JACKTRIP,
                node_a_id=node_a_id,
                node_b_id=node_b_id,
                status=LinkStatus.DESIRED_UP,
                params_json=params or {},
            )
            session.add(link)
            session.flush()  # Get link_id
            
            # Create voice command bundle if requested
            if create_voice_bundle:
                voice_bundle = FabricBundle(
                    link_id=link.link_id,
                    name="voice_cmd",
                    directionality=Directionality.BIDIR,
                    channels=2,
                    format="float32",
                )
                session.add(voice_bundle)
            
            # Update graph version
            graph.version += 1
            graph.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.info(
                "audio_link_created",
                link_id=link.link_id,
                node_a=node_a_id,
                node_b=node_b_id,
            )
            
            return link
            
        except Exception as e:
            session.rollback()
            logger.error("audio_link_creation_failed", error=str(e))
            raise
        finally:
            session.close()
    
    def create_midi_link(
        self,
        node_a_id: str,
        node_b_id: str,
        params: Optional[dict] = None,
    ) -> FabricLink:
        """Create a MIDI link between two nodes."""
        session = self.db.get_session()
        
        try:
            graph = self.ensure_default_graph()
            
            # Check if link already exists
            existing = (
                session.query(FabricLink)
                .filter_by(
                    graph_id=graph.graph_id,
                    link_type=LinkType.MIDI_RTP,
                )
                .filter(
                    ((FabricLink.node_a_id == node_a_id) & (FabricLink.node_b_id == node_b_id))
                    | ((FabricLink.node_a_id == node_b_id) & (FabricLink.node_b_id == node_a_id))
                )
                .first()
            )
            
            if existing:
                logger.warning("midi_link_exists", link_id=existing.link_id)
                return existing
            
            # Create link
            link = FabricLink(
                graph_id=graph.graph_id,
                link_type=LinkType.MIDI_RTP,
                node_a_id=node_a_id,
                node_b_id=node_b_id,
                status=LinkStatus.DESIRED_UP,
                params_json=params or {},
            )
            session.add(link)
            
            # Update graph version
            graph.version += 1
            graph.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.info(
                "midi_link_created",
                link_id=link.link_id,
                node_a=node_a_id,
                node_b=node_b_id,
            )
            
            return link
            
        except Exception as e:
            session.rollback()
            logger.error("midi_link_creation_failed", error=str(e))
            raise
        finally:
            session.close()
    
    def remove_link(self, link_id: str) -> bool:
        """Remove a link from the fabric graph."""
        session = self.db.get_session()
        
        try:
            link = session.query(FabricLink).filter_by(link_id=link_id).first()
            
            if not link:
                logger.warning("link_not_found", link_id=link_id)
                return False
            
            # Get graph for version update
            graph = session.query(FabricGraph).filter_by(graph_id=link.graph_id).first()
            
            # Delete link (cascades to bundles and attachments)
            session.delete(link)
            
            # Update graph version
            if graph:
                graph.version += 1
                graph.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.info("link_removed", link_id=link_id)
            return True
            
        except Exception as e:
            session.rollback()
            logger.error("link_removal_failed", error=str(e), link_id=link_id)
            return False
        finally:
            session.close()
    
    def list_links(self, graph_id: Optional[str] = None) -> List[FabricLink]:
        """List all links in a graph."""
        session = self.db.get_session()
        
        try:
            if graph_id:
                return session.query(FabricLink).filter_by(graph_id=graph_id).all()
            else:
                graph = self.get_graph()
                if graph:
                    return session.query(FabricLink).filter_by(graph_id=graph.graph_id).all()
                return []
        finally:
            session.close()
    
    def get_link(self, link_id: str) -> Optional[FabricLink]:
        """Get a link by ID."""
        session = self.db.get_session()
        try:
            return session.query(FabricLink).filter_by(link_id=link_id).first()
        finally:
            session.close()
