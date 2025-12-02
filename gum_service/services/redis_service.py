"""Redis-backed observation queue service.

Handles storage and retrieval of observations from Redis, organized by user.
Uses JSON serialization for observations.

Key structure: user:{username}:{user_id}:observations
Example: user:vinee:1:observations -> [obs1, obs2, obs3, ...]
"""

import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

import redis

logger = logging.getLogger("gum.api.redis")


class RedisObservationService:
    """Service for managing observations in Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Initialize Redis connection.
        
        Args:
            redis_url: Redis connection URL (default: localhost:6379, db=0)
        """
        self.redis_url = redis_url
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.logger = logger
        
        # Test connection
        try:
            self.client.ping()
            self.logger.info("Connected to Redis")
        except redis.ConnectionError as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _get_observation_key(self, user_id: str) -> str:
        """Generate Redis key for user's observations.
        
        Args:
            user_id: User ID from database
            
        Returns:
            Redis key string: user:{user_id}:observations
        """
        return f"user:{user_id}:observations"

    def add_observation(
        self,
        user_id: str,
        observer_name: str,
        content: str,
        content_type: str = "text",
        observation_id: Optional[str] = None,
    ) -> str:
        """Add an observation to Redis queue for a user.
        
        Args:
            user_id: User ID from database
            observer_name: Name of the observer that captured this observation
            content: The observation content
            content_type: Type of content (default: "text")
            observation_id: Optional UUID for the observation (auto-generated if not provided)
            
        Returns:
            Observation ID (UUID string)
        """
        if not observation_id:
            observation_id = str(__import__("uuid").uuid4())
        
        key = self._get_observation_key(user_id)
        
        observation = {
            "id": observation_id,
            "observer_name": observer_name,
            "content": content,
            "content_type": content_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Push to Redis list (LPUSH adds to left/head of list)
        self.client.lpush(key, json.dumps(observation))
        
        # Set expiration on the key (24 hours)
        self.client.expire(key, 24 * 3600)
        
        self.logger.debug(
            f"Added observation {observation_id} for user :{user_id} "
            f"(queue size: {self.client.llen(key)})"
        )

        print(f"Added observation {observation_id} for user :{user_id}" f"(queue size: {self.client.llen(key)})")
        
        return observation_id

    def get_observations(
        self, user_id: str, count: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch observations from Redis for a user.
        
        Args:
            user_id: User ID from database
            count: Number of observations to fetch (default: all)
            
        Returns:
            List of observation dictionaries, newest first
        """
        key = self._get_observation_key(user_id)
        
        # Get all observations (LRANGE with -count to 0 gets newest first)
        if count:
            # LRANGE key 0 (count-1) gets newest count items
            items = self.client.lrange(key, 0, count - 1)
        else:
            # LRANGE key 0 -1 gets all items
            items = self.client.lrange(key, 0, -1)
        
        observations = [json.loads(item) for item in items]
        
        self.logger.debug(
            f"Fetched {len(observations)} observations for user :{user_id}"
        )
        
        return observations

    def get_queue_size(self, user_id: str) -> int:
        """Get number of observations pending for a user.
        
        Args:
            user_id: User ID from database
            
        Returns:
            Number of observations in queue
        """
        key = self._get_observation_key(user_id)
        size = self.client.llen(key)
        return size

    def clear_observations(self, user_id: str) -> int:
        """Clear all observations for a user from Redis.
        
        Args:
            user_id: User ID from database
            
        Returns:
            Number of observations cleared
        """
        key = self._get_observation_key(user_id)
        count = self.client.llen(key)
        self.client.delete(key)
        
        self.logger.info(
            f"Cleared {count} observations for user :{user_id}"
        )
        
        return count

    def pop_observations(
        self, user_id: str, count: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch and remove observations from Redis (atomic operation).
        
        Useful for batch processing - gets observations and removes them in one call.
        
        Args:
            user_id: User ID from database
            count: Number of observations to pop (default: all)
            
        Returns:
            List of observation dictionaries (newest first), then removes from queue
        """
        key = self._get_observation_key(user_id)
        
        # Get all observations first
        if count:
            items = self.client.lrange(key, 0, count - 1)
        else:
            items = self.client.lrange(key, 0, -1)
        
        observations = [json.loads(item) for item in items]
        
        # Remove the fetched items
        if observations:
            if count:
                # LTRIM keeps only items after position (count-1)
                self.client.ltrim(key, count, -1)
            else:
                # Delete the entire key
                self.client.delete(key)
        
        self.logger.debug(
            f"Popped {len(observations)} observations for user :{user_id}"
        )
        
        return observations

    def get_all_pending_users(self) -> list[str]:
        """Get all user_ids with pending observations in Redis (key: user:{user_id}:observations)."""
        pattern = "user:*:observations"
        user_ids = []
        for key in self.client.scan_iter(match=pattern):
            # Parse key format: user:{user_id}:observations
            parts = key.split(":")
            if len(parts) == 3 and parts[0] == "user" and parts[2] == "observations":
                user_id = parts[1]
                user_ids.append(user_id)
        self.logger.debug(f"Found {len(user_ids)} users with pending observations")
        return user_ids

    def health_check(self) -> bool:
        """Check if Redis is healthy.
        
        Returns:
            True if Redis is accessible, False otherwise
        """
        try:
            self.client.ping()
            return True
        except redis.ConnectionError:
            return False
