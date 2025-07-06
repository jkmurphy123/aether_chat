import asyncio
import time
import random
import os
import sys

# Import your custom modules
from .display_manager import DisplayManager
from .mqtt_client import MQTTClient
from .llm_interface import GeminiLLMInterface
# Only import the MCPServerManager class. The 'mcp' object is now managed within it.
from .mcp_server import MCPServerManager 


# Imports for Gemini types (needed for constructing messages and tool responses)
# These come from google.generativeai.types
from google.genai.types import Content, Part


# --- Configuration Constants ---
BROKER_IP = "192.168.40.185" # <<< IMPORTANT: SET THIS TO YOUR MOSQUITTO BROKER'S IP ADDRESS
                       # For local Windows testing: "127.0.0.1"
                       # For Pi to Pi: IP of the Pi running Mosquitto (e.g., "192.168.1.100")
MQTT_PORT = 1883

# Make sure to set this for each Pi: "pi1" on one, "pi2" on the other.
# It prioritizes environment variable, then command line arg, then defaults.
THIS_PI_ID = os.getenv("PI_ID", None) # Default to None first, then check sys.argv
if THIS_PI_ID is None and len(sys.argv) > 1:
    THIS_PI_ID = sys.argv[1]
elif THIS_PI_ID is None:
    THIS_PI_ID = "pi1" # Final fallback if no env var and no arg

IDLE_MODE_MIN_DURATION_SEC = 30   # Reduced for quicker testing (originally 300)
IDLE_MODE_MAX_DURATION_SEC = 60   # Reduced for quicker testing (originally 1800)
CHAT_MODE_MIN_DURATION_SEC = 60   # Reduced for quicker testing (originally 60)
CHAT_MODE_MAX_DURATION_SEC = 600   # Reduced for quicker testing (originally 600)

# Timeout for other Pi's status to be considered online (heartbeat interval is 5s)
OTHER_PI_STATUS_TIMEOUT_SEC = 120 # If no heartbeat for 20s, assume offline (originally 120)

MESSAGE_DISPLAY_DELAY_SEC = 20 

# Predefined screensaver messages (you can make this more dynamic later)
SCREENSAVER_MESSAGES = [
    "Awaiting inspiration...",
    "Dreaming of algorithms...",
    "What's your favorite byte?",
    "Processing thoughts...",
    "The universe is vast. So are my possibilities.",
    "Ready for the next byte of wisdom."
]

# Predefined chat topics for initiation if LLM topic generation is too slow or complex
PREDEFINED_CHAT_TOPICS = [
    "the ethics of AI",
    "the future of quantum computing",
    "the nature of consciousness",
    "the most interesting unsolved mystery in science",
    "the role of art in an AI-driven world",
    "the perfect pizza topping", # For a lighter topic!
]

class ChatPiApp:
    def __init__(self, pi_id: str, broker_ip: str, mqtt_port: int):
        self.pi_id = pi_id
        self.broker_ip = broker_ip
        self.mqtt_port = mqtt_port

        self.display_manager = DisplayManager()
        # The message_callback will be a method of this class
        self.mqtt_client = MQTTClient(
            broker_ip=self.broker_ip,
            port=self.mqtt_port,
            pi_id=self.pi_id,
            message_callback=self._handle_incoming_chat_message,  # Links MQTT to main app
            maintain_heartbeat=True # Add this flag.  You'll implement in MQTTClient.
        )
        self.llm_interface = GeminiLLMInterface()

        # Initialize the MCP Server Manager, passing the real dependencies.
        # The `mcp` instance is now an attribute of `mcp_server_manager`.
        self.mcp_server_manager = MCPServerManager(
            pi_id=self.pi_id,
            display_manager=self.display_manager,
            mqtt_client=self.mqtt_client
        )

        self.mode = "IDLE"
        self.chat_duration_timer_task = None
        self.chat_partner_id = "pi2" if self.pi_id == "pi1" else "pi1" # Simple hardcoded partner
        self.current_chat_topic = ""
        self.chat_history = [] # Stores (role, content) for the current conversation
        self.is_chatting_with_llm = False # Flag to prevent multiple LLM calls simultaneously
        self.incoming_chat_queue = asyncio.Queue() # Queue for MQTT messages

        print(f"ChatPiApp initialized for Pi ID: {self.pi_id}")

    async def _handle_incoming_chat_message(self, message: str):
        """Callback for MQTTClient to put messages into the queue."""
        await self.incoming_chat_queue.put(message)
        print(f"[{self.pi_id}] Queued incoming message: {message[:50]}...")

    async def _process_incoming_messages(self):
        """Asynchronously process messages from the queue."""
        while True:
            message = await self.incoming_chat_queue.get()
            print(f"[{self.pi_id}] Processing MQTT message: {message[:50]}...")

            if self.mode == "IDLE":
                # If in idle mode, receiving a message means the other Pi is initiating
                print(f"[{self.pi_id}] Received message in IDLE mode. Switching to CHAT mode.")
                await self.enter_chat_mode(initiating=False, received_message=message)
            elif self.mode == "CHAT":
                # If in chat mode, feed the message to the LLM
                await self._chat_turn(message)
            self.incoming_chat_queue.task_done()

    async def run_screensaver(self):
        """Manages the screensaver display in IDLE mode."""
        while self.mode == "IDLE":
            message = random.choice(SCREENSAVER_MESSAGES)
            self.display_manager.display_screensaver_text(message)
            await asyncio.sleep(random.uniform(5, 15)) # Change message every 5-15 seconds

    async def enter_idle_mode(self):
        """Transitions the Pi to IDLE mode."""
        print(f"[{self.pi_id}] Entering IDLE mode.")
        self.mode = "IDLE"
        if self.chat_duration_timer_task:
            self.chat_duration_timer_task.cancel()
            self.chat_duration_timer_task = None
        self.chat_history = [] # Clear chat history
        self.current_chat_topic = ""
        self.display_manager.clear_screen() # Clear chat messages
        self.mqtt_client.publish_current_chat_topic("") # Clear topic broadcast (empty string means no topic)

        # Start screensaver task (ensure it's not started multiple times)
        # Check if there's already an active screensaver task
        if not hasattr(self, '_screensaver_task') or self._screensaver_task.done():
            self._screensaver_task = asyncio.create_task(self.run_screensaver())

        # Set a timer to potentially switch to chat mode
        idle_duration = random.randint(IDLE_MODE_MIN_DURATION_SEC, IDLE_MODE_MAX_DURATION_SEC)
        print(f"[{self.pi_id}] Staying in IDLE mode for {idle_duration} seconds.")
        
        try:
            await asyncio.sleep(idle_duration) # Wait for idle duration
        except asyncio.CancelledError:
            print(f"[{self.pi_id}] IDLE mode sleep cancelled.")
            return # Exit if cancelled (e.g., by immediate chat initiation)

        # After idle duration, try to initiate chat
        print(f"[{self.pi_id}] IDLE mode timer expired. Attempting to enter CHAT mode.")
        await self.enter_chat_mode(initiating=True)


    async def enter_chat_mode(self, initiating: bool, received_message: str = None):
        """Transitions the Pi to CHAT mode."""
        print(f"[{self.pi_id}] Attempting to enter CHAT mode (initiating={initiating}).")

        # Check if the other Pi is online before starting a chat
        if not self.mqtt_client.is_other_pi_online(self.chat_partner_id, max_age_seconds=OTHER_PI_STATUS_TIMEOUT_SEC):
            print(f"[{self.pi_id}] Other Pi ({self.chat_partner_id}) is offline. Cannot start chat. Returning to IDLE.")
            # If a screensaver task exists and is not done, cancel it before re-entering idle
            if hasattr(self, '_screensaver_task') and not self._screensaver_task.done():
                self._screensaver_task.cancel()
            await self.enter_idle_mode() # Re-enter idle if partner not found
            return
        
        # If there's an active screensaver task, cancel it.
        if hasattr(self, '_screensaver_task') and not self._screensaver_task.done():
            self._screensaver_task.cancel()
            await asyncio.sleep(0.1) # Give it a moment to cancel

        self.mode = "CHAT"
        self.display_manager.clear_screen() # Clear screensaver

        # Set a timer to eventually return to idle mode
        chat_duration = random.randint(CHAT_MODE_MIN_DURATION_SEC, CHAT_MODE_MAX_DURATION_SEC)
        print(f"[{self.pi_id}] CHAT mode will last for {chat_duration} seconds.")
        self.chat_duration_timer_task = asyncio.create_task(
            self._chat_timer(chat_duration)
        )

        if initiating:
            # Step 1: Pi A decides to start a new chat
            self.display_manager.display_message(f"[{self.pi_id}] Initiating chat...")
            self.current_chat_topic = random.choice(PREDEFINED_CHAT_TOPICS)
            
            print(f"[{self.pi_id}] Chat topic: {self.current_chat_topic}")
            self.mqtt_client.publish_current_chat_topic(self.current_chat_topic)

            initial_prompt_text = (
                f"You are an autonomous Raspberry Pi chatbot with ID '{self.pi_id}'. "
                f"You are starting a conversation with another autonomous Raspberry Pi chatbot "
                f"with ID '{self.chat_partner_id}'. The topic is: '{self.current_chat_topic}'. "
                "Begin the conversation with an engaging opening statement, keeping it concise. "
                "Use the 'send_chat_message_to_other_pi' tool to send your opening message to the other Pi."
            )
            # Pass raw text, _chat_turn will convert it to Part objects.
            await self._chat_turn(initial_prompt_text, role="system") 
            
        else: # Responding to an incoming message while in IDLE
            self.display_manager.display_message(f"[{self.pi_id}] Responding to chat...")
            print(f"[{self.pi_id}] Received initial message: {received_message}")
            
            # --- TODO: Implement `get_other_pi_topic` in MQTTClient to retrieve topic ---
            # For now, if responding, assume the other Pi has broadcasted its topic or infer.
            # You'll need to modify mqtt_client.py to store received topics and provide a getter.
            self.current_chat_topic = "general conversation" # Fallback
            # Example: self.current_chat_topic = self.mqtt_client.get_current_topic_from(self.chat_partner_id)
            # --- END TODO ---

            print(f"[{self.pi_id}] Current topic (inferred/default): {self.current_chat_topic}")

            # Feed the received message to the LLM to generate a response
            # Pass raw text, _chat_turn will convert it to Part objects.
            await self._chat_turn(received_message, role="user") 

    async def _chat_timer(self, duration: int):
        """Manages the duration of the CHAT mode."""
        try:
            await asyncio.sleep(duration)
        except asyncio.CancelledError:
            print(f"[{self.pi_id}] CHAT mode timer cancelled.")
            return # Exit if cancelled (e.g., by shutdown)

        print(f"[{self.pi_id}] CHAT mode timer expired. Returning to IDLE mode.")
        # Send a polite goodbye message before returning to idle
        try:
            goodbye_message_prompt = (
                f"You are an autonomous chatbot. The conversation with '{self.chat_partner_id}' "
                "about '{self.current_chat_topic}' is concluding. Send a brief, polite "
                "farewell message to them using the 'send_chat_message_to_other_pi' tool."
            )
            # Use a dummy role or new role if it's not a user/system prompt
            await self._chat_turn(goodbye_message_prompt, role="system_farewell")
        except Exception as e:
            print(f"[{self.pi_id}] Error sending farewell message: {e}")
        
        await self.enter_idle_mode()

    async def _chat_turn(self, incoming_message_text: str, role: str = "user"):
        """Manages a single turn of the conversation with the LLM."""
        if self.is_chatting_with_llm:
            print(f"[{self.pi_id}] LLM is currently busy, skipping turn.")
            return

        self.is_chatting_with_llm = True
        self.display_manager.display_message(f"[{self.pi_id}] Thinking...", font_size=40)

        # Build messages for LLM
        messages_for_llm = []
        
        # --- System Instruction is now a separate parameter in generate_response_with_tools ---
        system_instruction_text = (
            f"You are an autonomous Raspberry Pi chatbot with ID '{self.pi_id}'. "
            f"Your conversation partner is another autonomous Raspberry Pi chatbot with ID '{self.chat_partner_id}'. "
            f"The current topic of discussion is: '{self.current_chat_topic}'. "
            "Keep your responses concise and relevant to the topic. "
            "Use the provided tools only when appropriate to display messages or send them to the other Pi."
        )
        # --- END System Instruction ---
        
        # Add historical chat turns
        messages_for_llm.extend(self.chat_history)
        
        # Add the current incoming message if it's from the user (other Pi) or a system-initiated prompt
        if role == "user":
             messages_for_llm.append(Content(role="user", parts=[Part(text=incoming_message_text)]))
             # Display incoming message from other Pi on screen
             self.display_manager.display_message(
                f"[{self.chat_partner_id}]: {incoming_message_text}\n\n[{self.pi_id}]: Thinking...",
                font_size=40
            )
        elif role == "system": # For initial chat initiation (first prompt to LLM)
             messages_for_llm.append(Content(role="user", parts=[Part(text=incoming_message_text)]))
        elif role == "system_farewell": # For sending farewell message
             messages_for_llm.append(Content(role="user", parts=[Part(text=incoming_message_text)]))


        # Call LLM with tools
        callable_genai_tools = self.mcp_server_manager.get_all_genai_callable_tools()
        
        try:
            response_content = await self.llm_interface.generate_response_with_tools(
                messages_history=messages_for_llm,
                tools=callable_genai_tools, # Pass the list of callable functions directly
                system_instruction=system_instruction_text # Pass system instruction as separate arg
            )
            
            # Process LLM's response
            if response_content and response_content.parts:
                for part in response_content.parts:
                    print(f"test: {part}")
                    if part.function_call:
                        tool_name = part.function_call.name
                        tool_args = part.function_call.args
                        print(f"[{self.pi_id}] LLM requested tool call: {tool_name} with args {tool_args}")
                        
                        registered_tool_func = self.mcp_server_manager.mcp.get_tool_function(tool_name)
                        if tool_name in self.mcp_server_manager.genai_callable_tools_map:
                            registered_tool_func = self.mcp_server_manager.genai_callable_tools_map[tool_name]
                            tool_output = await registered_tool_func(**tool_args)
                            print(f"[{self.pi_id}] Tool '{tool_name}' executed. Output: {tool_output}")
                            self.chat_history.append(
                                Content(role="function", parts=[Part(function_response={"name": tool_name, "content": tool_output})])
                            )
                        else:
                            print(f"[{self.pi_id}] Error: LLM requested unknown tool: {tool_name}")
                            self.chat_history.append(
                                Content(role="function", parts=[Part(function_response={"name": tool_name, "content": f"Error: Unknown tool {tool_name}"})])
                            )
                    
                    elif part.text:
                        print(f"[{self.pi_id}] LLM Text Response (main.py): {part.text[:50]}...")
                        self.chat_history.append(Content(role="model", parts=[Part(text=part.text)]))
                        self.display_manager.display_message(
                            f"[{self.pi_id}]: {part.text}", font_size=40
                        )
                        await asyncio.sleep(MESSAGE_DISPLAY_DELAY_SEC) # Delay here                       
            else:
                print(f"[{self.pi_id}] LLM response had no text or tool calls.")
                self.display_manager.display_message(f"[{self.pi_id}] AI had no response or was blocked.", font_size=40)


        except Exception as e:
            print(f"[{self.pi_id}] Error during chat turn: {e}")
            import traceback
            traceback.print_exc() # Print full traceback for errors in chat turn
            self.display_manager.display_message(f"[{self.pi_id}] Error: Something went wrong with AI.", font_size=40)
        finally:
            self.is_chatting_with_llm = False
            self.chat_history = self.chat_history[-20:]

    async def start(self):
        """Main entry point for the application."""
        print(f"[{self.pi_id}] Starting ChatPiApp...")
        self.display_manager.display_screensaver_text(f"Pi {self.pi_id} Booting...")

        # Connect MQTT client
        self.mqtt_client.connect()
        # Publish online status and set a Last Will and Testament for proper offline status
        # Note: LWT is set in MQTTClient.__init__ typically, not on publish.
        self.mqtt_client.publish_status(is_online=True) 

        # Start background tasks
        asyncio.create_task(self._process_incoming_messages()) # Process MQTT messages

        # Initial mode entry
        await self.enter_idle_mode() # This will kick off the mode loop

    async def stop(self):
        """Gracefully stops the application."""
        print(f"[{self.pi_id}] Stopping ChatPiApp...")
        self.mqtt_client.publish_status(is_online=False) # Announce offline
        await asyncio.sleep(1) # Give time for last MQTT message to send
        self.mqtt_client.disconnect()
        self.display_manager.quit()
        print(f"[{self.pi_id}] ChatPiApp stopped.")

# --- Main execution block ---
if __name__ == "__main__":
    # Get PI_ID from environment variable or command line arguments
    # Prefer env var for deployment, then cmd arg for quick testing, then default.
    current_pi_id = os.getenv("PI_ID", None)
    if current_pi_id is None and len(sys.argv) > 1:
        current_pi_id = sys.argv[1]
    elif current_pi_id is None:
        current_pi_id = "pi1" # Default if no env var and no cmd arg

    print(f"Running application as Pi ID: {current_pi_id}")

    app = ChatPiApp(
        pi_id=current_pi_id,
        broker_ip=BROKER_IP,
        mqtt_port=MQTT_PORT
    )

    try:
        # asyncio.run() runs the top-level async function until it completes.
        asyncio.run(app.start())
    except KeyboardInterrupt:
        print(f"\n[{current_pi_id}] Ctrl+C detected. Shutting down application gracefully.")
        asyncio.run(app.stop()) # Call stop method gracefully
    except Exception as e:
        print(f"[{current_pi_id}] An unhandled error occurred: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for unhandled exceptions
        asyncio.run(app.stop()) # Attempt graceful shutdown