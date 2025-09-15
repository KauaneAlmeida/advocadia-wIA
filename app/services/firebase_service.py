"""
Firebase Service

This module handles all Firebase Firestore operations including:
- User session management
- Conversation flow storage and retrieval
- Lead data persistence
- Service status monitoring
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# Configure logging
logger = logging.getLogger(__name__)

# Global Firebase app and db instances
firebase_app = None
db = None

def initialize_firebase():
    """Initialize Firebase Admin SDK."""
    global firebase_app, db
    
    try:
        if firebase_app is not None:
            logger.info("✅ Firebase already initialized")
            return
        
        # Get Firebase credentials
        cred_path = os.getenv("FIREBASE_CREDENTIALS", "/firebase-key.json")
        
        if os.path.exists(cred_path):
            logger.info(f"📁 Loading Firebase credentials from {cred_path}")
            cred = credentials.Certificate(cred_path)
        else:
            # Try environment variables
            project_id = os.getenv("FIREBASE_PROJECT_ID")
            client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
            private_key = os.getenv("FIREBASE_PRIVATE_KEY")
            
            if not all([project_id, client_email, private_key]):
                raise ValueError("Firebase credentials not found in file or environment variables")
            
            # Fix private key formatting
            private_key = private_key.replace('\\n', '\n')
            
            cred_dict = {
                "type": "service_account",
                "project_id": project_id,
                "client_email": client_email,
                "private_key": private_key,
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID", ""),
                "client_id": os.getenv("FIREBASE_CLIENT_ID", ""),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email}"
            }
            
            logger.info("🔑 Loading Firebase credentials from environment variables")
            cred = credentials.Certificate(cred_dict)
        
        # Initialize Firebase app
        firebase_app = firebase_admin.initialize_app(cred)
        db = firestore.client()
        
        logger.info("✅ Firebase initialized successfully")
        
        # Test connection
        test_doc = db.collection('_health_check').document('test')
        test_doc.set({'timestamp': datetime.now(timezone.utc), 'status': 'healthy'})
        logger.info("✅ Firebase connection test successful")
        
    except Exception as e:
        logger.error(f"❌ Error initializing Firebase: {str(e)}")
        raise

async def get_firebase_service_status() -> Dict[str, Any]:
    """Get Firebase service status."""
    try:
        global db
        
        if db is None:
            return {
                "service": "firebase",
                "status": "not_initialized",
                "error": "Firebase not initialized"
            }
        
        # Test Firestore connection
        test_doc = db.collection('_health_check').document('test')
        test_doc.set({'timestamp': datetime.now(timezone.utc), 'status': 'healthy'})
        
        return {
            "service": "firebase",
            "status": "active",
            "implementation": "firebase_admin_sdk",
            "features": [
                "firestore_database",
                "user_sessions",
                "conversation_flows",
                "lead_management",
                "real_time_updates"
            ],
            "collections": [
                "user_sessions",
                "conversation_flows", 
                "leads",
                "_health_check"
            ]
        }
        
    except Exception as e:
        logger.error(f"❌ Firebase status check failed: {str(e)}")
        return {
            "service": "firebase",
            "status": "error",
            "error": str(e)
        }

async def get_conversation_flow() -> Dict[str, Any]:
    """Get conversation flow from Firestore."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        doc_ref = db.collection('conversation_flows').document('law_firm_intake')
        doc = doc_ref.get()
        
        if doc.exists:
            flow_data = doc.to_dict()
            logger.info("📋 Conversation flow loaded from Firestore")
            return flow_data
        else:
            # Create default flow
            default_flow = {
                "steps": [
                    {
                        "id": 1,
                        "question": "Olá! Para começar, qual é o seu nome completo?",
                        "field": "step_1",
                        "required": True,
                        "error_message": "Por favor, informe seu nome completo."
                    },
                    {
                        "id": 2,
                        "question": "Em qual área do direito você precisa de ajuda?\n\n• Penal\n• Civil\n• Trabalhista\n• Família\n• Empresarial",
                        "field": "step_2", 
                        "required": True,
                        "error_message": "Por favor, escolha uma das áreas: Penal, Civil, Trabalhista, Família ou Empresarial."
                    },
                    {
                        "id": 3,
                        "question": "Por favor, descreva brevemente sua situação ou problema jurídico.",
                        "field": "step_3",
                        "required": True,
                        "error_message": "Por favor, descreva sua situação com mais detalhes."
                    },
                    {
                        "id": 4,
                        "question": "Gostaria de agendar uma consulta com nosso advogado especializado? (Sim ou Não)",
                        "field": "step_4",
                        "required": True,
                        "error_message": "Por favor, responda Sim ou Não."
                    }
                ],
                "completion_message": "Perfeito! Suas informações foram registradas com sucesso. Nossa equipe especializada analisará seu caso e entrará em contato em breve para agendar sua consulta.",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            
            # Save default flow
            doc_ref.set(default_flow)
            logger.info("📋 Default conversation flow created in Firestore")
            return default_flow
            
    except Exception as e:
        logger.error(f"❌ Error getting conversation flow: {str(e)}")
        raise

async def get_user_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get user session from Firestore."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        doc_ref = db.collection('user_sessions').document(session_id)
        doc = doc_ref.get()
        
        if doc.exists:
            session_data = doc.to_dict()
            logger.debug(f"📖 Session {session_id} loaded from Firestore")
            return session_data
        else:
            logger.debug(f"📖 Session {session_id} not found")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error getting user session {session_id}: {str(e)}")
        return None

async def save_user_session(session_id: str, session_data: Dict[str, Any]) -> bool:
    """Save user session to Firestore."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        # Ensure timestamps are timezone-aware
        if 'created_at' in session_data and session_data['created_at']:
            if session_data['created_at'].tzinfo is None:
                session_data['created_at'] = session_data['created_at'].replace(tzinfo=timezone.utc)
        
        if 'last_updated' in session_data and session_data['last_updated']:
            if session_data['last_updated'].tzinfo is None:
                session_data['last_updated'] = session_data['last_updated'].replace(tzinfo=timezone.utc)
        
        doc_ref = db.collection('user_sessions').document(session_id)
        doc_ref.set(session_data, merge=True)
        
        logger.debug(f"💾 Session {session_id} saved to Firestore")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error saving user session {session_id}: {str(e)}")
        return False

async def save_lead_data(lead_data: Dict[str, Any]) -> str:
    """Save lead data to Firestore."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        # Add metadata
        lead_data.update({
            "created_at": datetime.now(timezone.utc),
            "status": "new",
            "source": "chatbot"
        })
        
        # Save to leads collection
        doc_ref = db.collection('leads').document()
        doc_ref.set(lead_data)
        
        lead_id = doc_ref.id
        logger.info(f"💾 Lead {lead_id} saved to Firestore")
        return lead_id
        
    except Exception as e:
        logger.error(f"❌ Error saving lead data: {str(e)}")
        raise

async def update_lead_data(lead_id: str, update_data: Dict[str, Any]) -> bool:
    """Update existing lead data."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        update_data['updated_at'] = datetime.now(timezone.utc)
        
        doc_ref = db.collection('leads').document(lead_id)
        doc_ref.update(update_data)
        
        logger.info(f"💾 Lead {lead_id} updated in Firestore")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error updating lead {lead_id}: {str(e)}")
        return False

async def get_leads(limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get leads from Firestore."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        query = db.collection('leads').order_by('created_at', direction=firestore.Query.DESCENDING).limit(limit)
        
        if status:
            query = query.where(filter=FieldFilter('status', '==', status))
        
        docs = query.stream()
        
        leads = []
        for doc in docs:
            lead_data = doc.to_dict()
            lead_data['id'] = doc.id
            leads.append(lead_data)
        
        logger.info(f"📋 Retrieved {len(leads)} leads from Firestore")
        return leads
        
    except Exception as e:
        logger.error(f"❌ Error getting leads: {str(e)}")
        return []

async def delete_old_sessions(days_old: int = 7) -> int:
    """Delete old user sessions."""
    try:
        global db
        
        if db is None:
            raise Exception("Firebase not initialized")
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        
        query = db.collection('user_sessions').where(
            filter=FieldFilter('created_at', '<', cutoff_date)
        ).limit(100)
        
        docs = query.stream()
        deleted_count = 0
        
        for doc in docs:
            doc.reference.delete()
            deleted_count += 1
        
        logger.info(f"🗑️ Deleted {deleted_count} old sessions")
        return deleted_count
        
    except Exception as e:
        logger.error(f"❌ Error deleting old sessions: {str(e)}")
        return 0

# Initialize Firebase on module import
try:
    initialize_firebase()
except Exception as e:
    logger.warning(f"⚠️ Firebase initialization failed on import: {str(e)}")