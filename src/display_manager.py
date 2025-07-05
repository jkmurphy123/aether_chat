import pygame
import os
import textwrap # Python's built-in text wrapping utility

# --- Configuration Constants ---
# You can adjust these
SCREEN_WIDTH = 1920  # Assuming standard Full HD. Adjust to your monitor's native resolution
SCREEN_HEIGHT = 1080 # Assuming standard Full HD. Adjust to your monitor's native resolution
BACKGROUND_COLOR = (20, 20, 40) # Dark blue/purple
TEXT_COLOR = (255, 255, 255)  # White
SCREENSAVER_TEXT_COLOR = (150, 150, 200) # Lighter blue/purple
DEFAULT_FONT_SIZE = 48
MESSAGE_LINE_SPACING = 10 # Pixels between lines of wrapped text
MARGIN = 50 # Margin from the edge of the screen

class DisplayManager:
    def __init__(self):
        # Initialize Pygame modules
        pygame.init()
        pygame.font.init() # Initialize font module explicitly

        # Set up the display for full screen without borders
        # We try to get the desktop size first for more robust full-screen
        try:
            info = pygame.display.Info()
            current_w, current_h = info.current_w, info.current_h
            if current_w > 0 and current_h > 0:
                print(f"Detected display resolution: {current_w}x{current_h}")
                self.screen_width = current_w
                self.screen_height = current_h
            else:
                print(f"Could not detect display resolution, falling back to configured: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
                self.screen_width = SCREEN_WIDTH
                self.screen_height = SCREEN_HEIGHT
        except pygame.error:
            print(f"Pygame display info not available, falling back to configured: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
            self.screen_width = SCREEN_WIDTH
            self.screen_height = SCREEN_HEIGHT

        # Set SDL environment variable to remove window borders on Linux (Raspberry Pi)
        # This can help ensure true fullscreen without a title bar
        os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0" # Position window at top-left
        os.environ['SDL_VIDEO_FBCON_MMAL'] = "0" # Disable Pi's HW acceleration for simpler display, might help stability.

        self.screen = pygame.display.set_mode(
            (self.screen_width, self.screen_height),
            pygame.FULLSCREEN | pygame.NOFRAME # FULLSCREEN for full screen, NOFRAME for no window borders
        )
        pygame.display.set_caption("Pi-to-Pi ChatBot") # Title, though won't be visible in NOFRAME mode

        # Cache fonts to avoid re-loading them
        self.fonts = {}
        self.load_font(DEFAULT_FONT_SIZE) # Load default font size

    def load_font(self, size):
        """Loads and caches a font for a given size."""
        if size not in self.fonts:
            # Try to use a common system font, or Pygame's default if not found
            try:
                # Prioritize fonts common on Linux/Raspberry Pi OS
                font_path = pygame.font.match_font('dejavusans, liberationmono, freesans')
                if font_path:
                    self.fonts[size] = pygame.font.Font(font_path, size)
                else:
                    # Fallback to Pygame's default font if no system font found
                    self.fonts[size] = pygame.font.Font(None, size)
            except Exception as e:
                print(f"Error loading system font: {e}. Falling back to default Pygame font.")
                self.fonts[size] = pygame.font.Font(None, size)
        return self.fonts[size]

    def clear_screen(self):
        """Clears the entire screen with the background color."""
        self.screen.fill(BACKGROUND_COLOR)

    def display_message(self, message: str, color=TEXT_COLOR, font_size=DEFAULT_FONT_SIZE, y_start_pos=MARGIN):
        """
        Displays a multi-line message on the screen, wrapping text if necessary.
        Messages are drawn from y_start_pos downwards.
        """
        self.clear_screen()
        font = self.load_font(font_size)

        # Calculate the maximum width available for text
        max_text_width = self.screen_width - (2 * MARGIN)

        # Use textwrap to split the message into lines that fit the width
        # The 'width' parameter in textwrap refers to character count,
        # but font.size() is in pixels. We need to approximate character width.
        # A simple estimation: assume average character width is about half of font_size.
        # This will need calibration.
        avg_char_width = font_size * 0.6 # Rough estimation for proportional fonts
        wrap_char_width = int(max_text_width / avg_char_width)

        wrapped_lines = textwrap.wrap(message, width=wrap_char_width)

        current_y = y_start_pos
        for line in wrapped_lines:
            # Render each line
            text_surface = font.render(line, True, color) # True for anti-aliasing
            
            # Calculate x position to center the text
            x_pos = (self.screen_width - text_surface.get_width()) // 2
            
            self.screen.blit(text_surface, (x_pos, current_y))
            current_y += text_surface.get_height() + MESSAGE_LINE_SPACING # Move down for the next line

        pygame.display.flip() # Update the entire screen

    def display_screensaver_text(self, text: str):
        """Displays a single line of text for the screensaver, centered."""
        self.clear_screen()
        font = self.load_font(DEFAULT_FONT_SIZE)
        text_surface = font.render(text, True, SCREENSAVER_TEXT_COLOR)

        # Center the text
        x_pos = (self.screen_width - text_surface.get_width()) // 2
        y_pos = (self.screen_height - text_surface.get_height()) // 2

        self.screen.blit(text_surface, (x_pos, y_pos))
        pygame.display.flip()

    def update_display(self):
        """Call this after all drawing operations to update the screen."""
        pygame.display.flip() # Or pygame.display.update() for partial updates

    def quit(self):
        """Properly quits pygame."""
        pygame.quit()

# --- Example Usage (for testing this module independently) ---
if __name__ == "__main__":
    display_manager = DisplayManager()

    # Test Idle Mode / Screensaver
    print("Displaying screensaver text...")
    display_manager.display_screensaver_text("Pi-Bot Chat 🤖")
    pygame.time.wait(3000) # Wait 3 seconds

    # Test Chat Mode message (single line)
    print("Displaying a short message...")
    display_manager.display_message("Hello from the Raspberry Pi! I'm ready to chat.", color=(0, 255, 0))
    pygame.time.wait(3000)

    # Test Chat Mode message (multi-line, wrapped)
    long_message = (
        "This is a much longer message that should demonstrate how "
        "the text wrapping functionality works. Pygame doesn't "
        "natively wrap text, so we use Python's 'textwrap' module "
        "to break the message into lines before rendering each one "
        "individually onto the screen. This ensures readability "
        "even when the AI generates very verbose responses. "
        "We also center each line horizontally for a clean look."
    )
    print("Displaying a long, wrapped message...")
    display_manager.display_message(long_message, color=(255, 255, 0), font_size=36)
    pygame.time.wait(6000)

    print("Quitting display manager...")
    display_manager.quit()
    print("Display manager quit successfully.")