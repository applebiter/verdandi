"""
Verdandi Rune - CLI entry point.
"""

import sys
import argparse
import structlog

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database


logger = structlog.get_logger()


def cmd_status(args):
    """Show node status."""
    config = VerdandiConfig.load()
    
    print("Verdandi Node Status")
    print("=" * 50)
    print(f"Node ID:         {config.node.node_id}")
    print(f"Hostname:        {config.node.hostname}")
    print(f"Display Name:    {config.node.display_name or '(not set)'}")
    print(f"Personality:     {config.node.personality_name or '(not set)'}")
    print(f"\nDaemon:")
    print(f"  Host:          {config.daemon.grpc_host}")
    print(f"  Port:          {config.daemon.grpc_port}")
    print(f"  mDNS:          {'enabled' if config.daemon.enable_mdns else 'disabled'}")
    print(f"\nDatabase:")
    print(f"  Host:          {config.database.host}")
    print(f"  Port:          {config.database.port}")
    print(f"  Database:      {config.database.database}")
    
    # Test database connection
    try:
        db = Database(config.database)
        print(f"  Status:        ✓ Connected")
    except Exception as e:
        print(f"  Status:        ✗ Error: {e}")


def cmd_init_db(args):
    """Initialize database schema."""
    from verdandi_codex.db_init import init_database
    
    if args.drop:
        confirm = input("⚠️  This will DROP ALL TABLES. Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return
    
    init_database(drop_existing=args.drop)


def cmd_config(args):
    """Show or edit configuration."""
    config = VerdandiConfig.load()
    
    if args.edit:
        config_file = VerdandiConfig.get_config_file()
        import os
        editor = os.getenv("EDITOR", "nano")
        os.system(f"{editor} {config_file}")
    else:
        import yaml
        print(yaml.dump(config.to_dict(), default_flow_style=False, sort_keys=False))


def cmd_certs(args):
    """Manage certificates."""
    from verdandi_codex.crypto import NodeCertificateManager
    
    config = VerdandiConfig.load()
    cert_manager = NodeCertificateManager()
    
    if args.init:
        # Initialize certificates
        created = cert_manager.ensure_node_certificate(
            config.node.node_id,
            config.node.hostname,
        )
        if created:
            print("✓ Certificates created successfully")
        else:
            print("✓ Certificates already exist")
        
        paths = cert_manager.get_certificate_paths()
        print(f"\nCA Certificate:   {paths['ca_cert']}")
        print(f"Node Certificate: {paths['node_cert']}")
        print(f"Node Key:         {paths['node_key']}")
    
    elif args.show:
        paths = cert_manager.get_certificate_paths()
        fingerprint = cert_manager.get_certificate_fingerprint()
        
        print("Certificate Status")
        print("=" * 50)
        print(f"CA Certificate:   {paths['ca_cert']}")
        print(f"Node Certificate: {paths['node_cert']}")
        print(f"Node Key:         {paths['node_key']}")
        print(f"\nFingerprint:      {fingerprint or '(not found)'}")


def main():
    """Main CLI entry point."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    
    parser = argparse.ArgumentParser(
        description="Verdandi Rune - CLI for Verdandi operations"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Status command
    parser_status = subparsers.add_parser("status", help="Show node status")
    parser_status.set_defaults(func=cmd_status)
    
    # Init-db command
    parser_init_db = subparsers.add_parser("init-db", help="Initialize database schema")
    parser_init_db.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing tables (DESTRUCTIVE)",
    )
    parser_init_db.set_defaults(func=cmd_init_db)
    
    # Config command
    parser_config = subparsers.add_parser("config", help="Show or edit configuration")
    parser_config.add_argument(
        "--edit",
        action="store_true",
        help="Edit configuration file in $EDITOR",
    )
    parser_config.set_defaults(func=cmd_config)
    
    # Certs command
    parser_certs = subparsers.add_parser("certs", help="Manage certificates")
    parser_certs.add_argument(
        "--init",
        action="store_true",
        help="Initialize/create certificates",
    )
    parser_certs.add_argument(
        "--show",
        action="store_true",
        help="Show certificate information",
    )
    parser_certs.set_defaults(func=cmd_certs)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        args.func(args)
        return 0
    except Exception as e:
        logger.error("command_failed", command=args.command, error=str(e), exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
