import asyncio
import logging
from .observer import Observer
from ..schemas import Update

class TextObserver(Observer):
    """Observer that processes text input for proposition generation.
    
    This observer allows text to be added programmatically and converts it
    into observations that are batched for proposition generation.
    """

    def __init__(self, name: str = "TextObserver"):
        """Initialize the TextObserver.
        
        Args:
            name (str, optional): Name of the observer. Defaults to "TextObserver".
        """
        self._input_queue = asyncio.Queue()
        self.logger = logging.getLogger("TextObserver")
        super().__init__(name)

    async def add_text(self, text: str):
        """Add text input to be processed.
        
        Args:
            text (str): Text to process and generate propositions from.
        """
        await self._input_queue.put(text)

    async def _worker(self):
        """Main worker method that processes text from the input queue.
        
        Continuously reads text from the input queue and converts it into
        Update objects that are put on the update_queue for the main GUM
        system to process.
        """
        while self._running:
            try:
                text = await self._input_queue.get()
                update = Update(content=text, content_type="input_text")
                await self.update_queue.put(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error processing text: {e}")

    async def stop(self):
        """Stop the observer and clean up resources.
        
        Overrides the base class stop method to properly clean up.
        """
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Drain the input queue
        while not self._input_queue.empty():
            self._input_queue.get_nowait()
        # Call parent stop to drain update queue
        await super().stop()  