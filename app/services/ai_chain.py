"""
AI Chain Service with LangChain Integration

This module provides LangChain-based conversation management with memory,
system prompts, and Gemini AI integration for the law firm chatbot.
"""

import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime

# LangChain imports
from langchain.memory import ConversationBufferWindowMemory
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser

# Configure logging
logger = logging.getLogger(__name__)

# Legal AI System Prompt
LEGAL_AI_SYSTEM_PROMPT = """
Você é um assistente jurídico especializado em direito brasileiro, trabalhando para um escritório de advocacia.

INSTRUÇÕES IMPORTANTES:
1. Responda SEMPRE em português brasileiro
2. Seja profissional, empático e prestativo
3. Forneça informações jurídicas gerais, mas sempre recomende consulta presencial
4. Mantenha respostas concisas (máximo 3 parágrafos)
5. Use linguagem acessível, evitando jargões excessivos
6. Sempre inclua disclaimer sobre necessidade de consulta jurídica personalizada

ÁREAS DE ESPECIALIZAÇÃO:
- Direito Civil
- Direito Penal
- Direito Trabalhista
- Direito de Família
- Direito Empresarial

FORMATO DE RESPOSTA:
- Seja direto e objetivo
- Use emojis moderadamente (máximo 2 por resposta)
- Termine sempre sugerindo agendamento de consulta

DISCLAIMER OBRIGATÓRIO:
Sempre mencione que as informações são gerais e que cada caso requer análise específica.
"""

class AIOrchestrator:
    """
    AI Orchestrator using LangChain with conversation memory and Gemini integration.
    """
    
    def __init__(self):
        self.conversations: Dict[str, Any] = {}
        self.model = None
        self.initialize_model()
    
    def initialize_model(self):
        """Initialize Gemini model via LangChain."""
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("⚠️ GEMINI_API_KEY not configured")
                return
            
            self.model = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=api_key,
                temperature=0.7,
                max_tokens=500,
                timeout=15
            )
            logger.info("✅ Gemini model initialized via LangChain")
            
        except Exception as e:
            logger.error(f"❌ Error initializing Gemini model: {str(e)}")
            self.model = None
    
    def get_or_create_memory(self, session_id: str) -> ConversationBufferWindowMemory:
        """Get or create conversation memory for session."""
        if session_id not in self.conversations:
            self.conversations[session_id] = {
                "memory": ConversationBufferWindowMemory(
                    k=6,  # Keep last 6 exchanges
                    return_messages=True,
                    memory_key="chat_history"
                ),
                "created_at": datetime.now(),
                "message_count": 0
            }
            logger.info(f"🧠 Created new memory for session {session_id}")
        
        return self.conversations[session_id]["memory"]
    
    def clear_memory(self, session_id: str):
        """Clear conversation memory for session."""
        if session_id in self.conversations:
            del self.conversations[session_id]
            logger.info(f"🗑️ Cleared memory for session {session_id}")
    
    async def generate_response(
        self, 
        message: str, 
        session_id: str = "default",
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate AI response using LangChain with conversation memory.
        """
        try:
            if not self.model:
                logger.error("❌ Gemini model not initialized")
                return self._get_fallback_response()
            
            # Get conversation memory
            memory = self.get_or_create_memory(session_id)
            
            # Create prompt template with system message and memory
            prompt = ChatPromptTemplate.from_messages([
                ("system", LEGAL_AI_SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}")
            ])
            
            # Create chain
            chain = (
                RunnablePassthrough.assign(
                    chat_history=lambda x: memory.chat_memory.messages
                )
                | prompt
                | self.model
                | StrOutputParser()
            )
            
            # Add context to input if provided
            input_data = {"input": message}
            if context:
                context_str = self._format_context(context)
                input_data["input"] = f"Contexto: {context_str}\n\nPergunta: {message}"
            
            logger.info(f"🤖 Generating response for session {session_id}")
            
            # Generate response
            response = await chain.ainvoke(input_data)
            
            # Save to memory
            memory.save_context(
                {"input": message},
                {"output": response}
            )
            
            # Update conversation stats
            self.conversations[session_id]["message_count"] += 1
            self.conversations[session_id]["last_updated"] = datetime.now()
            
            logger.info(f"✅ Response generated for session {session_id}")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error generating AI response: {str(e)}")
            return self._get_fallback_response()
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context information for the AI."""
        context_parts = []
        
        if context.get("user_name"):
            context_parts.append(f"Nome do cliente: {context['user_name']}")
        
        if context.get("legal_area"):
            context_parts.append(f"Área jurídica: {context['legal_area']}")
        
        if context.get("situation"):
            context_parts.append(f"Situação: {context['situation']}")
        
        if context.get("previous_responses"):
            context_parts.append(f"Respostas anteriores: {context['previous_responses']}")
        
        return " | ".join(context_parts) if context_parts else "Nenhum contexto adicional"
    
    def _get_fallback_response(self) -> str:
        """Fallback response when AI is unavailable."""
        return (
            "Obrigado pela sua mensagem! 🙏 "
            "No momento estou com dificuldades técnicas, mas nossa equipe "
            "analisará sua solicitação e entrará em contato em breve. "
            "Para urgências, entre em contato diretamente conosco."
        )
    
    def get_conversation_summary(self, session_id: str) -> Dict[str, Any]:
        """Get conversation summary for session."""
        if session_id not in self.conversations:
            return {"exists": False}
        
        conv = self.conversations[session_id]
        memory = conv["memory"]
        
        return {
            "exists": True,
            "session_id": session_id,
            "message_count": conv["message_count"],
            "created_at": conv["created_at"],
            "last_updated": conv.get("last_updated"),
            "memory_length": len(memory.chat_memory.messages),
            "recent_messages": [
                {
                    "type": "human" if isinstance(msg, HumanMessage) else "ai",
                    "content": msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                }
                for msg in memory.chat_memory.messages[-4:]  # Last 4 messages
            ]
        }
    
    async def get_service_status(self) -> Dict[str, Any]:
        """Get AI service status."""
        try:
            gemini_configured = bool(os.getenv("GEMINI_API_KEY"))
            model_initialized = self.model is not None
            
            # Test model if configured
            model_working = False
            if model_initialized:
                try:
                    test_response = await self.generate_response(
                        "Teste de conexão", 
                        session_id="health_check"
                    )
                    model_working = bool(test_response and len(test_response) > 10)
                    # Clean up test session
                    self.clear_memory("health_check")
                except Exception:
                    model_working = False
            
            status = "active" if (gemini_configured and model_initialized and model_working) else "configuration_required"
            
            return {
                "service": "ai_chain_service",
                "status": status,
                "implementation": "langchain_gemini",
                "model": "gemini-1.5-flash",
                "features": {
                    "conversation_memory": True,
                    "system_prompts": True,
                    "context_support": True,
                    "session_management": True,
                    "fallback_responses": True
                },
                "configuration": {
                    "gemini_api_key_configured": gemini_configured,
                    "model_initialized": model_initialized,
                    "model_working": model_working
                },
                "active_sessions": len(self.conversations),
                "memory_window": 6,
                "max_tokens": 500,
                "temperature": 0.7
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting AI service status: {str(e)}")
            return {
                "service": "ai_chain_service",
                "status": "error",
                "error": str(e)
            }


# Global AI orchestrator instance
ai_orchestrator = AIOrchestrator()

# Service functions for external use
async def process_chat_message(
    message: str, 
    session_id: str = "default",
    context: Optional[Dict[str, Any]] = None
) -> str:
    """Process chat message using AI orchestrator."""
    return await ai_orchestrator.generate_response(message, session_id, context)

def clear_conversation_memory(session_id: str):
    """Clear conversation memory for session."""
    ai_orchestrator.clear_memory(session_id)

def get_conversation_summary(session_id: str) -> Dict[str, Any]:
    """Get conversation summary for session."""
    return ai_orchestrator.get_conversation_summary(session_id)

async def get_ai_service_status() -> Dict[str, Any]:
    """Get AI service status."""
    return await ai_orchestrator.get_service_status()