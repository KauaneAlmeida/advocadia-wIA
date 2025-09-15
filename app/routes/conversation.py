"""
Conversation Routes

Handles conversation flow endpoints using the Clean Orchestrator service.
Provides endpoints for starting conversations, processing responses, and managing sessions.
"""

from fastapi import APIRouter, HTTPException, status
from app.models.request import ConversationRequest
from app.models.response import ConversationResponse
from app.services.orchestration_service import clean_orchestrator
import logging
import uuid

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

@router.post("/conversation/start", response_model=ConversationResponse)
async def start_conversation():
    """
    Start a new conversation session.
    Returns the first question in the intake flow.
    """
    try:
        # Generate new session ID
        session_id = f"web_{uuid.uuid4().hex[:12]}"
        
        logger.info(f"🚀 Starting new conversation: {session_id}")
        
        # Get the first question from Firebase flow
        from app.services.firebase_service import get_conversation_flow
        flow = await get_conversation_flow()
        
        if not flow or not flow.get("steps"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Conversation flow not configured"
            )
        
        first_step = flow["steps"][0]
        
        return ConversationResponse(
            session_id=session_id,
            question=first_step["question"],
            step_id=first_step["id"],
            is_final_step=len(flow["steps"]) == 1,
            flow_completed=False,
            ai_mode=False,
            phone_collected=False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error starting conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start conversation"
        )

@router.post("/conversation/respond", response_model=ConversationResponse)
async def process_conversation_response(request: ConversationRequest):
    """
    Process user response in the conversation flow.
    Uses Clean Orchestrator for intelligent message handling.
    """
    try:
        logger.info(f"📝 Processing response for session: {request.session_id}")
        logger.debug(f"Message: {request.message}")
        
        # Use session_id from request or generate new one
        session_id = request.session_id or f"web_{uuid.uuid4().hex[:12]}"
        
        # Process message through Clean Orchestrator
        result = await clean_orchestrator.process_message(
            message=request.message,
            session_id=session_id,
            platform="web"
        )
        
        # Convert orchestrator result to API response
        response = ConversationResponse(
            session_id=result["session_id"],
            flow_completed=result.get("flow_completed", False),
            ai_mode=result.get("ai_mode", False),
            phone_collected=result.get("phone_collected", False)
        )
        
        # Set response content based on result type
        if result.get("response_type") == "firebase_step":
            response.question = result["response"]
            response.step_id = result.get("current_step")
            response.is_final_step = result.get("step_advanced", False) and result.get("flow_completed", False)
            
        elif result.get("response_type") == "firebase_redirect":
            response.question = result["response"]
            response.step_id = result.get("current_step")
            response.redirect_message = True
            
        elif result.get("response_type") == "phone_collected":
            response.response = result["response"]
            response.phone_collected = True
            response.flow_completed = True
            
        else:
            # AI mode or other response types
            response.response = result["response"]
            response.ai_mode = True
        
        logger.info(f"✅ Response processed for session: {session_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing conversation response: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process conversation response"
        )

@router.post("/conversation/submit-phone")
async def submit_phone_number(phone_number: str, session_id: str):
    """
    Submit phone number for WhatsApp integration.
    """
    try:
        logger.info(f"📱 Processing phone submission for session: {session_id}")
        
        result = await clean_orchestrator.handle_phone_number_submission(
            phone_number=phone_number,
            session_id=session_id
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error submitting phone number: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit phone number"
        )

@router.get("/conversation/status/{session_id}")
async def get_conversation_status(session_id: str):
    """
    Get current conversation status for a session.
    """
    try:
        logger.info(f"📊 Getting status for session: {session_id}")
        
        context = await clean_orchestrator.get_session_context(session_id)
        
        if not context.get("exists"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        return context
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting conversation status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get conversation status"
        )

@router.get("/conversation/flow")
async def get_conversation_flow_endpoint():
    """
    Get the current conversation flow configuration.
    """
    try:
        from app.services.firebase_service import get_conversation_flow
        flow = await get_conversation_flow()
        
        return {
            "flow": flow,
            "total_steps": len(flow.get("steps", [])),
            "source": "firebase_firestore"
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting conversation flow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get conversation flow"
        )