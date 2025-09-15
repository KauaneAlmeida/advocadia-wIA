"""
Intelligent Orchestration Service

This service implements a clean separation between Firebase (structured flow) 
and Gemini AI (conversational responses) with proper fallback handling.

Orchestration Logic:
1. Firebase as main flow controller (source of truth for steps)
2. Off-topic message handling with brief human-like responses
3. Fallback handling (last resort for failures)

Flow: User message → Orchestrator → [Firebase OR Gemini OR Fallback]
"""

import logging
import json
import os
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from app.services.firebase_service import (
    get_user_session,
    save_user_session,
    save_lead_data,
    get_conversation_flow,
    get_firebase_service_status
)
from app.services.gemini_service import generate_gemini_response, get_gemini_service_status
from app.services.baileys_service import baileys_service

logger = logging.getLogger(__name__)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is UTC timezone aware."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class CleanOrchestrator:
    """
    Clean orchestration service with proper separation of concerns.
    Firebase handles structured flow, Gemini handles conversational responses.
    """

    def __init__(self):
        self.law_firm_number = "+5511918368812"
        self.flow_cache = None
        self.cache_timestamp = None
        
    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Get comprehensive service status."""
        try:
            # Check Firebase status
            firebase_status = await get_firebase_service_status()
            
            # Check Gemini AI status
            gemini_status = await get_gemini_service_status()
            
            # Determine overall status
            firebase_healthy = firebase_status.get("status") == "active"
            gemini_healthy = gemini_status.get("status") == "active"
            
            if firebase_healthy and gemini_healthy:
                overall_status = "active"
            elif firebase_healthy:
                overall_status = "degraded"  # Firebase works, AI doesn't
            else:
                overall_status = "error"  # Firebase issues are critical
            
            return {
                "overall_status": overall_status,
                "firebase_status": firebase_status,
                "gemini_status": gemini_status,
                "features": {
                    "structured_flow": firebase_healthy,
                    "ai_responses": gemini_healthy,
                    "fallback_mode": firebase_healthy and not gemini_healthy,
                    "whatsapp_integration": True,
                    "lead_collection": firebase_healthy
                },
                "orchestration_mode": "firebase_primary_gemini_secondary"
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting overall service status: {str(e)}")
            return {
                "overall_status": "error",
                "firebase_status": {"status": "error", "error": str(e)},
                "gemini_status": {"status": "error", "error": str(e)},
                "features": {},
                "error": str(e)
            }

    async def _get_conversation_flow(self) -> Dict[str, Any]:
        """Get conversation flow with 5-minute caching."""
        try:
            if (self.flow_cache is None or 
                self.cache_timestamp is None or
                (datetime.now(timezone.utc) - self.cache_timestamp).seconds > 300):
                
                self.flow_cache = await get_conversation_flow()
                self.cache_timestamp = datetime.now(timezone.utc)
                logger.info("📋 Conversation flow loaded from Firebase")
            
            return self.flow_cache
        except Exception as e:
            logger.error(f"❌ Error loading conversation flow: {str(e)}")
            # Return minimal default flow
            return {
                "steps": [
                    {"id": 1, "question": "Qual é o seu nome completo?"},
                    {"id": 2, "question": "Em qual área do direito você precisa de ajuda?"},
                    {"id": 3, "question": "Descreva brevemente sua situação."},
                    {"id": 4, "question": "Gostaria de agendar uma consulta?"}
                ],
                "completion_message": "Obrigado! Suas informações foram registradas."
            }

    async def _get_or_create_session(
        self,
        session_id: str,
        platform: str,
        phone_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get existing session or create new one."""
        session_data = await get_user_session(session_id)
        
        if not session_data:
            session_data = {
                "session_id": session_id,
                "platform": platform,
                "created_at": ensure_utc(datetime.now(timezone.utc)),
                "current_step": 1,
                "responses": {},
                "flow_completed": False,
                "phone_collected": False,
                "message_count": 0,
                "last_updated": ensure_utc(datetime.now(timezone.utc))
            }
            logger.info(f"🆕 Created new session {session_id} for platform {platform}")

        if phone_number:
            session_data["phone_number"] = phone_number

        return session_data

    def _is_phone_number(self, message: str) -> bool:
        """Check if message looks like a Brazilian phone number."""
        clean_message = ''.join(filter(str.isdigit, message))
        return len(clean_message) >= 10 and len(clean_message) <= 13

    def _get_off_topic_response(self, message: str, current_step: int) -> Optional[str]:
        """
        Generate brief, human-like responses for off-topic messages.
        Returns None if message is not off-topic.
        """
        message_lower = message.strip().lower()
        
        # Common off-topic patterns and responses
        off_topic_patterns = {
            # Price/Cost questions
            ('quanto custa', 'preço', 'valor', 'custo', 'honorário', 'cobrança'): 
                "Entendo sua preocupação sobre valores, mas vamos primeiro coletar suas informações. Discutiremos isso depois.",
            
            # Who will help questions
            ('quem vai', 'qual advogado', 'quem me ajuda', 'quem atende'): 
                "Um advogado especializado irá atendê-lo após coletarmos seus dados. Vamos continuar.",
            
            # When/timing questions
            ('quando', 'que horas', 'horário', 'prazo', 'demora'): 
                "Sobre prazos e horários, nossa equipe explicará tudo depois. Vamos finalizar seu cadastro primeiro.",
            
            # Where/location questions
            ('onde', 'endereço', 'localização', 'escritório'): 
                "Informações sobre localização serão fornecidas em breve. Vamos continuar com suas informações.",
            
            # How it works questions
            ('como funciona', 'como é', 'processo', 'procedimento'): 
                "Explicaremos todo o processo depois. Agora vamos focar em conhecer sua situação.",
            
            # General greetings/small talk
            ('como vai', 'tudo bem', 'boa tarde', 'boa noite', 'obrigado', 'valeu'): 
                "Obrigado! Vamos continuar com o atendimento.",
            
            # Experience/credentials questions
            ('experiência', 'formação', 'especialista', 'qualificação'): 
                "Nossa equipe é altamente qualificada. Vamos primeiro entender seu caso.",
            
            # Success rate questions
            ('taxa de sucesso', 'quantos casos', 'resultados'): 
                "Temos ótimos resultados, mas cada caso é único. Vamos conhecer o seu primeiro.",
            
            # Urgency expressions
            ('urgente', 'rápido', 'emergência', 'pressa'): 
                "Entendemos a urgência. Para agilizar, vamos completar suas informações rapidamente."
        }
        
        # Check if message matches any off-topic pattern
        for keywords, response in off_topic_patterns.items():
            if any(keyword in message_lower for keyword in keywords):
                logger.info(f"🔄 Off-topic message detected: {message[:30]}...")
                return response
        
        # Check for very short responses that might be greetings
        if len(message.strip()) <= 3 and message_lower in ['oi', 'olá', 'ok', 'sim', 'não']:
            return "Vamos continuar com o atendimento."
        
        # Not off-topic
        return None

    def _is_step_response(self, message: str, step_id: int) -> bool:
        """
        Validate if message is appropriate for current step.
        STRICT validation - must match step requirements exactly.
        """
        message = message.strip().lower()
        
        if not message or len(message) < 1:
            return False
            
        # STRICT step validation - no flexibility
        if step_id == 1:  # Name step
            # Must be at least 2 characters, look like a name
            return (len(message) >= 2 and 
                    not any(word in message for word in ['olá', 'oi', 'hello', 'como', 'ajuda', 'preciso', 'quero']))
                    
        elif step_id == 2:  # Area of law step
            # Must contain legal area keywords
            legal_areas = ['penal', 'civil', 'trabalhista', 'família', 'familia', 'empresarial', 
                          'criminal', 'trabalho', 'divórcio', 'divorcio', 'comercial', 'contrato']
            return (len(message) >= 3 and 
                    any(area in message for area in legal_areas))
                    
        elif step_id == 3:  # Situation description step
            # Must be at least 5 characters, not a greeting
            return (len(message) >= 5 and 
                    not any(word in message for word in ['olá', 'oi', 'como', 'você', 'qual', 'quando', 'ajuda']))
                    
        elif step_id == 4:  # Phone step
            # Must look like a phone number
            digits = ''.join(filter(str.isdigit, message))
            return len(digits) >= 10 and len(digits) <= 13
        
        return False

    def _validate_and_normalize_answer(self, answer: str, step_id: int) -> str:
        """Validate answer according to Firebase schema rules."""
        answer = answer.strip()
        
        if step_id == 1:  # Name
            if len(answer) < 2:
                raise ValueError("Nome muito curto")
            return " ".join(word.capitalize() for word in answer.split())
            
        elif step_id == 2:  # Area of law
            if len(answer) < 3:
                raise ValueError("Área não especificada")
            # Normalize according to schema
            area_map = {
                'criminal': 'Penal',
                'penal': 'Penal', 
                'trabalho': 'Trabalhista',
                'trabalhista': 'Trabalhista',
                'família': 'Família',
                'familia': 'Família',
                'divórcio': 'Família',
                'divorcio': 'Família',
                'civil': 'Civil',
                'empresarial': 'Empresarial',
                'comercial': 'Empresarial'
            }
            answer_lower = answer.lower()
            for key, value in area_map.items():
                if key in answer_lower:
                    return value
            # If no match found, it's invalid
            raise ValueError("Área jurídica não reconhecida")
            
        elif step_id == 3:  # Situation
            if len(answer) < 5:
                raise ValueError("Descrição muito curta")
            return answer
            
        elif step_id == 4:  # Phone
            digits = ''.join(filter(str.isdigit, answer))
            if len(digits) < 10 or len(digits) > 13:
                raise ValueError("Número de telefone inválido")
            return digits
        
        return answer

    async def _handle_firebase_step(
        self, 
        message: str, 
        session_data: Dict[str, Any]
    ) -> Tuple[str, bool]:
        """
        Handle Firebase step with STRICT validation.
        Returns (response, step_advanced)
        """
        try:
            session_id = session_data["session_id"]
            current_step = session_data.get("current_step", 1)
            
            logger.info(f"🔥 Firebase STRICT step {current_step} for session {session_id}")
            
            flow = await self._get_conversation_flow()
            steps = flow.get("steps", [])
            
            # Find current step
            current_step_data = next((s for s in steps if s["id"] == current_step), None)
            if not current_step_data:
                logger.error(f"❌ Step {current_step} not found in flow")
                return steps[0]["question"], False
            
            # STRICT validation - if invalid, repeat same question with error
            try:
                normalized_answer = self._validate_and_normalize_answer(message, current_step)
            except ValueError as e:
                logger.info(f"❌ Validation failed for step {current_step}: {str(e)}")
                error_message = current_step_data.get("error_message", current_step_data["question"])
                return error_message, False
            
            # Store valid answer
            field_name = current_step_data.get("field", f"step_{current_step}")
            
            # Store normalized answer
            session_data["last_updated"] = ensure_utc(datetime.now(timezone.utc))
            logger.info(f"💾 Valid answer stored for step {current_step}: {normalized_answer[:20]}...")
            
            # Find next step
            logger.info(f"💾 Answer stored for step {current_step}")
            next_step_data = next((s for s in steps if s["id"] == next_step), None)
            # Check for next step
            if next_step_data:
                # Advance to next step
                session_data["current_step"] = next_step
                await save_user_session(session_id, session_data)
                # Advance to next step - return EXACT question from Firebase
                logger.info(f"➡️ Advanced to step {next_step} for session {session_id}")
                return next_step_data["question"], True
                logger.info(f"➡️ Advanced to step {next_step}")
                session_data["flow_completed"] = True
                await save_user_session(session_id, session_data)
                # Flow completed - return EXACT completion_message from Firebase
                # Replace placeholders in completion message
                completion_msg = flow.get("completion_message", "Obrigado! Suas informações foram registradas.")
                responses = session_data.get("responses", {})
                # Replace placeholders in Firebase completion_message
                # Replace placeholders
                for field, value in responses.items():
                    placeholder = "{" + field + "}"
                # Replace Firebase placeholders
                
                logger.info(f"✅ Firebase flow completed for session {session_id}")
                return "Obrigado pelas informações! Para finalizar, preciso do seu número de WhatsApp com DDD (exemplo: 11999999999):", True
                logger.info(f"❌ Invalid input for step {current_step}")
                logger.info(f"✅ Flow completed for session {session_id}")
                return completion_msg, True
                
        except Exception as e:
            logger.error(f"❌ Firebase step error: {str(e)}")
            # Return current step question on error
            flow = await self._get_conversation_flow()
            steps = flow.get("steps", [])
            current_step = session_data.get("current_step", 1)
            current_step_data = next((s for s in steps if s["id"] == current_step), None)
            if current_step_data:
                return current_step_data["question"], False
            return "Qual é o seu nome completo?", False

    async def _handle_gemini_response(
        self, 
        message: str, 
        session_data: Dict[str, Any]
    ) -> str:
        """
        Handle off-topic messages with brief human-like responses.
        """
        try:
            current_step = session_data.get("current_step", 1)
            
            # Check if this is an off-topic message
            off_topic_response = self._get_off_topic_response(message, current_step)
            if off_topic_response:
                return off_topic_response
            
            # If not off-topic, redirect to current Firebase step
            flow = await self._get_conversation_flow()
            steps = flow.get("steps", [])
            current_step_data = next((s for s in steps if s["id"] == current_step), None)
            
            if current_step_data:
                return current_step_data["question"]
            return "Qual é o seu nome completo?"
                
        except Exception as e:
            logger.error(f"❌ Error handling off-topic message: {str(e)}")
            return "Qual é o seu nome completo?"

    async def _handle_gemini_response_old(
        self, 
        message: str, 
        session_data: Dict[str, Any]
    ) -> str:
        """
        DISABLED - Only Firebase flow allowed.
        Return current Firebase step question.
        """
        try:
            session_id = session_data["session_id"]
            logger.info(f"🚫 Gemini disabled - redirecting to Firebase for session {session_id}")
            
            # Get current Firebase step and return its question
            current_step = session_data.get("current_step", 1)
            flow = await self._get_conversation_flow()
            steps = flow.get("steps", [])
            current_step_data = next((s for s in steps if s["id"] == current_step), None)
            
            if current_step_data:
                return current_step_data["question"]
            return "Qual é o seu nome completo?"
                
        except Exception as e:
            logger.error(f"❌ Error getting Firebase step: {str(e)}")
            return "Qual é o seu nome completo?"

    def _get_fallback_response(self) -> str:
        """Return first Firebase step question as fallback."""
        return "Qual é o seu nome completo?"

    async def _handle_phone_collection(
        self, 
        phone_message: str, 
        session_id: str, 
        session_data: Dict[str, Any]
    ) -> str:
        """Handle phone number collection and send WhatsApp message."""
        try:
            # Clean and validate phone number
            phone_clean = ''.join(filter(str.isdigit, phone_message))
            
            if len(phone_clean) < 10 or len(phone_clean) > 13:
                return "Número inválido. Por favor, digite no formato com DDD (exemplo: 11999999999):"

            # Format phone number for WhatsApp
            if len(phone_clean) == 10:
                phone_formatted = f"55{phone_clean[:2]}9{phone_clean[2:]}"
            elif len(phone_clean) == 11:
                phone_formatted = f"55{phone_clean}"
            elif phone_clean.startswith("55"):
                phone_formatted = phone_clean
            else:
                phone_formatted = f"55{phone_clean}"

            whatsapp_number = f"{phone_formatted}@s.whatsapp.net"

            # Update session
            session_data.update({
                "phone_number": phone_clean,
                "phone_formatted": phone_formatted,
                "phone_collected": True,
                "last_updated": ensure_utc(datetime.now(timezone.utc))
            })
            await save_user_session(session_id, session_data)

            # Save lead data
            responses = session_data.get("responses", {})
            answers = []
            for i in range(1, 5):
                answer = responses.get(f"step_{i}", "")
                if answer:
                    answers.append({"id": i, "answer": answer})
            
            # Add phone as final answer
            answers.append({"id": 5, "answer": phone_clean})
            
            try:
                await save_lead_data({"answers": answers})
                logger.info(f"💾 Lead saved for session {session_id}")
            except Exception as save_error:
                logger.error(f"❌ Error saving lead: {str(save_error)}")

            # Prepare WhatsApp message
            user_name = responses.get("step_1", "Cliente")
            area = responses.get("step_2", "não informada")
            situation = responses.get("step_3", "não detalhada")[:150]

            whatsapp_message = f"""Olá {user_name}! 👋

Recebemos sua solicitação através do nosso site e estamos aqui para ajudá-lo com questões jurídicas.

Nossa equipe especializada está pronta para analisar seu caso.

📄 Resumo do caso:
- 👤 Nome: {user_name}
- 📌 Área: {area}
- 📝 Situação: {situation}

Nossa equipe entrará em contato em breve."""

            # Send WhatsApp message
            whatsapp_success = False
            try:
                await baileys_service.send_whatsapp_message(whatsapp_number, whatsapp_message)
                logger.info(f"📤 WhatsApp message sent to {phone_formatted}")
                whatsapp_success = True
            except Exception as whatsapp_error:
                logger.error(f"❌ Error sending WhatsApp: {str(whatsapp_error)}")

            # Return confirmation
            confirmation = f"""Número confirmado: {phone_clean} 📱

Perfeito! Suas informações foram registradas com sucesso. Nossa equipe entrará em contato em breve.

{'✅ Mensagem enviada para seu WhatsApp!' if whatsapp_success else '⚠️ Houve um problema ao enviar a mensagem do WhatsApp, mas suas informações foram salvas.'}"""

            return confirmation

        except Exception as e:
            logger.error(f"❌ Error handling phone collection: {str(e)}")
            return "Ocorreu um erro ao processar seu número. Por favor, tente novamente."

    async def process_message(
        self,
        message: str,
        session_id: str,
        phone_number: Optional[str] = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        Main orchestration logic: Firebase → Gemini → Fallback
        """
        try:
            logger.info(f"🎯 Orchestrating message - Session: {session_id}, Platform: {platform}")
            logger.info(f"📝 Message: '{message[:100]}...'")

            session_data = await self._get_or_create_session(session_id, platform, phone_number)
            session_data["message_count"] = session_data.get("message_count", 0) + 1

            # Handle phone collection (after flow completion)
            if (session_data.get("flow_completed") and 
                not session_data.get("phone_collected") and 
                self._is_phone_number(message)):
                
                logger.info(f"📱 Processing phone number submission")
                phone_response = await self._handle_phone_collection(message, session_id, session_data)
                return {
                    "response_type": "phone_collected",
                    "platform": platform,
                    "session_id": session_id,
                    "response": phone_response,
                    "phone_collected": True,
                    "message_count": session_data["message_count"]
                }

            # Skip structured flow for WhatsApp platform - use Gemini only
            if platform == "whatsapp":
                logger.info(f"📱 WhatsApp platform - using Gemini only")
                try:
                    ai_response = await self._handle_gemini_response(message, session_data)
                    session_data["last_updated"] = ensure_utc(datetime.now(timezone.utc))
                    await save_user_session(session_id, session_data)
                    
                    return {
                        "response_type": "gemini_whatsapp",
                        "platform": platform,
                        "session_id": session_id,
                        "response": ai_response,
                        "message_count": session_data["message_count"]
                    }
                except Exception as e:
                    logger.error(f"❌ WhatsApp Gemini error: {str(e)}")
                    return {
                        "response_type": "whatsapp_fallback",
                        "platform": platform,
                        "session_id": session_id,
                        "response": "Obrigado pela sua mensagem. Nossa equipe analisará e retornará em breve.",
                        "message_count": session_data["message_count"]
                    }

            # Web platform: Use orchestration logic
            current_step = session_data.get("current_step", 1)
            
            # Check if this is a valid Firebase step response
            if not session_data.get("flow_completed") and self._is_step_response(message, current_step):
                logger.info(f"🔥 Valid Firebase step {current_step} response")
                firebase_response, step_advanced = await self._handle_firebase_step(message, session_data)
                
                return {
                    "response_type": "firebase_step",
                    "platform": platform,
                    "session_id": session_id,
                    "response": firebase_response,
                    "current_step": session_data.get("current_step", current_step),
                    "step_advanced": step_advanced,
                    "flow_completed": session_data.get("flow_completed", False),
                    "message_count": session_data["message_count"]
                }
            
            # Invalid/off-topic response - redirect to current Firebase step
            else:
                logger.info(f"🔄 Off-topic/invalid message - handling with brief response")
                
                # Get current Firebase step question
                flow = await self._get_conversation_flow()
                steps = flow.get("steps", [])
                current_step_data = next((s for s in steps if s["id"] == current_step), None)
                
                # Handle off-topic message with brief response + current step question
                off_topic_response = self._get_off_topic_response(message, current_step)
                if off_topic_response and current_step_data:
                    # Combine brief off-topic response with current step question
                    combined_response = f"{off_topic_response}\n\n{current_step_data['question']}"
                else:
                    # Fallback to just the current step question
                    combined_response = current_step_data["question"] if current_step_data else "Qual é o seu nome completo?"
                
                session_data["last_updated"] = ensure_utc(datetime.now(timezone.utc))
                await save_user_session(session_id, session_data)
                
                return {
                    "response_type": "firebase_redirect",
                    "platform": platform,
                    "session_id": session_id,
                    "response": combined_response,
                    "current_step": session_data.get("current_step", current_step),
                    "flow_completed": session_data.get("flow_completed", False),
                    "off_topic_handled": bool(off_topic_response),
                    "message_count": session_data["message_count"]
                }

        except Exception as e:
            logger.error(f"❌ Orchestration error: {str(e)}")
            return {
                "response_type": "error",
                "platform": platform,
                "session_id": session_id,
                "response": "Qual é o seu nome completo?",
                "error": str(e)
            }

    async def handle_phone_number_submission(
        self,
        phone_number: str,
        session_id: str
    ) -> Dict[str, Any]:
        """Handle phone number submission from web interface."""
        try:
            session_data = await get_user_session(session_id) or {}
            response = await self._handle_phone_collection(phone_number, session_id, session_data)
            return {
                "status": "success",
                "message": response,
                "phone_collected": True
            }
        except Exception as e:
            logger.error(f"❌ Error in phone submission: {str(e)}")
            return {
                "status": "error",
                "message": "Erro ao processar número de WhatsApp",
                "error": str(e)
            }

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Get current session context and status."""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"exists": False}

            return {
                "exists": True,
                "session_id": session_id,
                "platform": session_data.get("platform", "unknown"),
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_collected": session_data.get("phone_collected", False),
                "responses": session_data.get("responses", {}),
                "message_count": session_data.get("message_count", 0),
                "created_at": session_data.get("created_at"),
                "last_updated": session_data.get("last_updated")
            }
        except Exception as e:
            logger.error(f"❌ Error getting session context: {str(e)}")
            return {"exists": False, "error": str(e)}


# Global instance
clean_orchestrator = CleanOrchestrator()

# Aliases for backward compatibility
intelligent_orchestrator = clean_orchestrator
hybrid_orchestrator = clean_orchestrator