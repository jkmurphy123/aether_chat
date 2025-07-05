import asyncio
import time
import random
import os
import sys

# Import your custom modules
from .display_manager import DisplayManager
from .mqtt_client import MQTTClient
from .llm_interface import GeminiLLMInterface
# Import the MCPServerManager class and the global 'mcp' object
from .mcp_server import MCPServerManager, mcp 
from google import genai
from google.genai import Tool
from google.genai.types import (
    GenerateContentConfig,
    FunctionCallingConfig,
    HarmCategory,
    HarmBlockThreshold,
    Content, # Re-import Content if not already
    Part     # Re-import Part if not already
)


# --- Configuration Constants ---
# You can define these in a separate config.py or use environment variables
# For simplicity, we'll put them here for now.
BROKER_IP = "192.168.40.185" # <<< IMPORTANT: REPLACE WITH YOUR BROKER IP
MQTT_PORT = 1883
# Make sure to set this for each Pi: "pi1" on one, "pi2" on the other
THIS_PI_ID = os.getenv("PI_ID", "pi1") # Use environment variable or default to "pi1"

IDLE_MODE_MIN_DURATION_SEC = 30  # 5 minutes
IDLE_MODE_MAX_DURATION_SEC = 60 # 30 minutes
CHAT_MODE_MIN_DURATION_SEC = 60   # 1 minute
CHAT_MODE_MAX_DURATION_SEC = 300  # 10 minutes

# Timeout for other Pi's status to be considered online
OTHER_PI_STATUS_TIMEOUT_SEC = 120 # 2 minutes

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
            message_callback=self._handle_incoming_chat_message # This links MQTT to main app
        )
        self.llm_interface = GeminiLLMInterface()

        # Initialize the MCP Server Manager, passing the real dependencies
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
        print(f"Queued incoming message: {message[:50]}...")

    async def _process_incoming_messages(self):
        """Asynchronously process messages from the queue."""
        while True:
            message = await self.incoming_chat_queue.get()
            print(f"[MainApp] Processing MQTT message: {message[:50]}...")

            if self.mode == "IDLE":
                # If in idle mode, receiving a message means the other Pi is initiating
                print(f"[MainApp] Received message in IDLE mode. Switching to CHAT mode.")
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
        self.mqtt_client.publish_current_chat_topic("") # Clear topic broadcast

        # Start screensaver task
        asyncio.create_task(self.run_screensaver())

        # Set a timer to potentially switch to chat mode
        idle_duration = random.randint(IDLE_MODE_MIN_DURATION_SEC, IDLE_MODE_MAX_DURATION_SEC)
        print(f"[{self.pi_id}] Staying in IDLE mode for {idle_duration} seconds.")
        await asyncio.sleep(idle_duration) # Wait for idle duration

        # After idle duration, try to initiate chat
        print(f"[{self.pi_id}] IDLE mode timer expired. Attempting to enter CHAT mode.")
        await self.enter_chat_mode(initiating=True)


    async def enter_chat_mode(self, initiating: bool, received_message: str = None):
        """Transitions the Pi to CHAT mode."""
        print(f"[{self.pi_id}] Attempting to enter CHAT mode (initiating={initiating}).")

        # Check if the other Pi is online before starting a chat
        if not self.mqtt_client.is_other_pi_online(self.chat_partner_id, max_age_seconds=OTHER_PI_STATUS_TIMEOUT_SEC):
            print(f"[{self.pi_id}] Other Pi ({self.chat_partner_id}) is offline. Cannot start chat. Returning to IDLE.")
            await self.enter_idle_mode() # Re-enter idle if partner not found
            return

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
            # Generate a random topic
            self.current_chat_topic = random.choice(PREDEFINED_CHAT_TOPICS) # Or use LLM to generate:
            # self.current_chat_topic = await self.llm_interface.generate_response("Generate a unique and interesting topic for two AI's to discuss (short and to the point).")
            
            print(f"[{self.pi_id}] Chat topic: {self.current_chat_topic}")
            self.mqtt_client.publish_current_chat_topic(self.current_chat_topic)

            initial_prompt = (
                f"You are an autonomous Raspberry Pi chatbot with ID '{self.pi_id}'. "
                f"You are starting a conversation with another autonomous Raspberry Pi chatbot "
                f"with ID '{self.chat_partner_id}'. The topic is: '{self.current_chat_topic}'. "
                "Begin the conversation with an engaging opening statement, keeping it concise. "
                "Use the 'send_chat_message_to_other_pi' tool to send your opening message to the other Pi."
            )
            await self._chat_turn(initial_prompt, role="system") # Use system role for initial setup
            
        else: # Responding to an incoming message while in IDLE
            self.display_manager.display_message(f"[{self.pi_id}] Responding to chat...")
            print(f"[{self.pi_id}] Received initial message: {received_message}")
            # If responding, assume the other Pi already broadcasted topic (or infer)
            # For simplicity, we might need a way to get the topic from the other Pi via MQTT if not broadcasted
            # For now, let's assume the other Pi will broadcast its topic or LLM can infer.
            self.current_chat_topic = self.mqtt_client.get_other_pi_topic(self.chat_partner_id) # Need to implement this in MQTTClient
            if not self.current_chat_topic:
                 # Fallback if topic not explicitly received, perhaps infer or use a generic one
                 self.current_chat_topic = "general conversation" 
                 print(f"[{self.pi_id}] Could not retrieve topic from partner, defaulting to '{self.current_chat_topic}'.")

            # Feed the received message to the LLM to generate a response
            await self._chat_turn(received_message, role="user") # Treat as a user message from other Pi

    async def _chat_timer(self, duration: int):
        """Manages the duration of the CHAT mode."""
        await asyncio.sleep(duration)
        print(f"[{self.pi_id}] CHAT mode timer expired. Returning to IDLE mode.")
        # Send a polite goodbye message before returning to idle
        try:
            goodbye_message_prompt = (
                f"You are an autonomous chatbot. The conversation with '{self.chat_partner_id}' "
                "about '{self.current_chat_topic}' is concluding. Send a brief, polite "
                "farewell message to them using the 'send_chat_message_to_other_pi' tool."
            )
            response = await self.llm_interface.generate_response(goodbye_message_prompt)
            # Assuming LLM will call send_chat_message_to_other_pi
            # If LLM doesn't call tool, you might send a default farewell message here.
        except Exception as e:
            print(f"Error sending farewell message: {e}")
        
        await self.enter_idle_mode()

    async def _chat_turn(self, incoming_message: str, role: str = "user"):
        """Manages a single turn of the conversation with the LLM."""
        if self.is_chatting_with_llm:
            print(f"[{self.pi_id}] LLM is currently busy, skipping turn.")
            return

        self.is_chatting_with_llm = True
        self.display_manager.display_message(f"[{self.pi_id}] Thinking...", font_size=40)

        # Add incoming message to history
        if role == "system":
            pass
        elif role == "user":
            self.chat_history.append({"role": "user", "parts": [{"text": incoming_message}]})
            self.display_manager.display_message(
                f"[{self.chat_partner_id}]: {incoming_message}\n\n[{self.pi_id}]: Thinking...",
                font_size=40
            )

        # Construct the full prompt for the LLM, including history and instructions
        messages_for_llm = [
            {"role": "system", "parts": [
                f"You are an autonomous Raspberry Pi chatbot with ID '{self.pi_id}'. "
                f"Your conversation partner is another autonomous Raspberry Pi chatbot with ID '{self.chat_partner_id}'. "
                f"The current topic of discussion is: '{self.current_chat_topic}'. "
                "Keep your responses concise and relevant to the topic. "
                "Use the provided tools only when appropriate to display messages or send them to the other Pi."
            ]}
        ]
        messages_for_llm.extend(self.chat_history)
        
        if role == "user":
             messages_for_llm.append({"role": "user", "parts": [{"text": incoming_message}]})
        elif role == "system":
             messages_for_llm.append({"role": "user", "parts": [{"text": incoming_message}]})

        # Call LLM with tools
        mcp_tool_objects = await self.mcp_server_manager.mcp.list_tools() # This returns FastMCP's internal Tool objects

        # --- CRITICAL FIX: Convert FastMCP.Tool objects into Gemini's expected FunctionDeclaration dictionaries.
        # This is the most direct and lowest-level conversion.
        gemini_function_declarations_list = []
        for mcp_tool_obj in mcp_tool_objects:
            # Each mcp_tool_obj is a FastMCP.Tool instance.
            # We construct a dictionary that matches Gemini's FunctionDeclaration schema.
            func_decl_dict = {
                "name": mcp_tool_obj.name,
                "description": mcp_tool_obj.description,
                "parameters": mcp_tool_obj.inputSchema # This should already be in the correct dict format
            }
            # Add a safeguard for uppercase types within parameters, if FastMCP provides them lowercase
            if 'properties' in func_decl_dict['parameters']:
                for prop_name, prop_details in func_decl_dict['parameters']['properties'].items():
                    if 'type' in prop_details and isinstance(prop_details['type'], str):
                        prop_details['type'] = prop_details['type'].upper()
            if 'type' in func_decl_dict['parameters'] and isinstance(func_decl_dict['parameters']['type'], str):
                func_decl_dict['parameters']['type'] = func_decl_dict['parameters']['type'].upper()

            gemini_function_declarations_list.append(func_decl_dict)

        # Now, wrap this list of FunctionDeclaration dictionaries into a single 'Tool' object for Gemini.
        # This 'Tool' object is a dictionary with the 'function_declarations' key.
        # This is the specific structure expected by the 'tools' parameter in GenerateContentConfig.
        
        final_tools_for_gemini_config = []
        if gemini_function_declarations_list: # Only add if there are actual tools
            final_tools_for_gemini_config.append({
                "function_declarations": gemini_function_declarations_list
            })

        # --- END CRITICAL FIX ---
        
        try:
            response_content = await self.llm_interface.generate_response_with_tools(
                messages=messages_for_llm,
                tools=final_tools_for_gemini_config # Pass the correctly structured list of tool dictionaries
            )
            
            # Process LLM's response
            if response_content and response_content.parts:
                for part in response_content.parts:
                    if part.function_call:
                        tool_name = part.function_call.name
                        tool_args = part.function_call.args
                        print(f"[{self.pi_id}] LLM requested tool call: {tool_name} with args {tool_args}")
                        
                        registered_tool_func = self.mcp_server_manager.mcp.get_tool_function(tool_name)
                        if registered_tool_func:
                            tool_output = await registered_tool_func(**tool_args)
                            print(f"[{self.pi_id}] Tool '{tool_name}' executed. Output: {tool_output}")
                            self.chat_history.append({
                                "role": "function",
                                "parts": [{"function_response": {"name": tool_name, "content": tool_output}}]
                            })
                        else:
                            print(f"[{self.pi_id}] Error: LLM requested unknown tool: {tool_name}")
                            self.chat_history.append({
                                "role": "function",
                                "parts": [{"function_response": {"name": tool_name, "content": f"Error: Unknown tool {tool_name}"}}]
                            })
                    
                    elif part.text:
                        print(f"[{self.pi_id}] LLM Text Response: {part.text[:50]}...")
                        self.chat_history.append({"role": "model", "parts": [{"text": part.text}]})
                        self.display_manager.display_message(
                            f"[{self.pi_id}]: {part.text}", font_size=40
                        )
            else:
                print(f"[{self.pi_id}] LLM response had no text or tool calls.")
                self.display_manager.display_message(f"[{self.pi_id}] AI had no response or was blocked.", font_size=40)


        except Exception as e:
            print(f"[{self.pi_id}] Error during chat turn: {e}")
            self.display_manager.display_message(f"[{self.pi_id}] Error: Something went wrong with AI.", font_size=40)
        finally:
            self.is_chatting_with_llm = False
            self.chat_history = self.chat_history[-20:]


    async def start(self):
        """Main entry point for the application."""
        print(f"Starting ChatPiApp for Pi ID: {self.pi_id}")
        self.display_manager.display_screensaver_text(f"Pi {self.pi_id} Booting...")

        # Connect MQTT client
        self.mqtt_client.connect()
        self.mqtt_client.publish_status(is_online=True) # Announce online status

        # Start background tasks
        asyncio.create_task(self._process_incoming_messages()) # Process MQTT messages

        # The MCP server runs as a separate component, its tools will be called by your LLM.
        # It's not directly running in a loop here, but its methods are callable.

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
    # Get PI_ID from command line arguments or environment variable
    # python src/main.py pi1
    # or export PI_ID=pi1 (on Linux) / $env:PI_ID="pi1" (on PowerShell)
    if len(sys.argv) > 1:
        current_pi_id = sys.argv[1]
    else:
        current_pi_id = os.getenv("PI_ID", "pi1") # Fallback if no arg and no env var

    # This is for testing on your Windows machine, so use localhost
    # When deployed to Pi, your Pi will connect to the other Pi's Mosquitto broker
    # if you chose to run it on one Pi. Or to a cloud broker.
    # For now, if you ran mosquitto on pi1, use its IP.
    # If running both main.py on same Windows machine, use localhost.
    broker_ip_to_use = "127.0.0.1" # For testing both instances on your Windows PC
    # Or, if Mosquitto is on Pi1 and this is Pi2's main.py, use Pi1's IP
    # broker_ip_to_use = "YOUR_PI1_MOSQUITTO_IP_HERE"

    app = ChatPiApp(
        pi_id=current_pi_id,
        broker_ip=BROKER_IP, # Use the configured BROKER_IP constant
        mqtt_port=MQTT_PORT
    )

    try:
        # asyncio.run() runs the top-level async function until it completes.
        # It also handles shutting down the event loop.
        asyncio.run(app.start())
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Shutting down application.")
        asyncio.run(app.stop()) # Call stop method gracefully
    except Exception as e:
        print(f"An unhandled error occurred: {e}")
        asyncio.run(app.stop()) # Attempt graceful shutdown