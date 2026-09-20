"""MongoDB connection pooling and client management."""

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from utils.logger import logger


class MongoConnection:
    """Manages MongoDB connection pooling and client lifecycle."""

    _instance: Optional['MongoConnection'] = None
    _client: Optional[AsyncIOMotorClient] = None
    _database: Optional[AsyncIOMotorDatabase] = None

    def __new__(cls) -> 'MongoConnection':
        """Singleton pattern - ensures only one connection instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def connect(cls, mongodb_url: str, database_name: str) -> AsyncIOMotorDatabase:
        """
        Establish MongoDB connection with connection pooling.

        Args:
            mongodb_url: MongoDB connection string (supports mongodb+srv://)
            database_name: Database name to connect to

        Returns:
            AsyncIOMotorDatabase instance ready for queries

        Raises:
            Exception: If connection fails
        """
        instance = cls()

        if instance._client is not None:
            logger.info("MongoDB connection already established")
            return instance._database

        try:
            # Create async client with connection pooling
            # maxPoolSize controls max concurrent connections
            # minPoolSize ensures pool has minimum connections ready
            instance._client = AsyncIOMotorClient(
                mongodb_url,
                maxPoolSize=50,
                minPoolSize=10,
                connectTimeoutMS=10000,
                serverSelectionTimeoutMS=5000,
                retryWrites=True,
            )

            # Verify connection by pinging the server
            await instance._client.admin.command('ping')

            instance._database = instance._client[database_name]
            logger.info(f"✓ MongoDB connection established (database: {database_name})")

            return instance._database

        except Exception as e:
            logger.error(f"✗ Failed to connect to MongoDB: {e}")
            raise

    @classmethod
    async def disconnect(cls) -> None:
        """
        Close MongoDB connection and cleanup resources.

        Should be called during application shutdown.
        """
        instance = cls()

        if instance._client is not None:
            try:
                instance._client.close()
                instance._client = None
                instance._database = None
                logger.info("✓ MongoDB connection closed")
            except Exception as e:
                logger.error(f"✗ Error closing MongoDB connection: {e}")
                raise

    @classmethod
    def get_database(cls) -> AsyncIOMotorDatabase:
        """
        Get the connected database instance.

        Returns:
            AsyncIOMotorDatabase instance

        Raises:
            RuntimeError: If not connected yet
        """
        instance = cls()

        if instance._database is None:
            raise RuntimeError(
                "MongoDB not connected. Call MongoConnection.connect() first"
            )

        return instance._database

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        """
        Get the MongoDB client instance.

        Returns:
            AsyncIOMotorClient instance

        Raises:
            RuntimeError: If not connected yet
        """
        instance = cls()

        if instance._client is None:
            raise RuntimeError(
                "MongoDB not connected. Call MongoConnection.connect() first"
            )

        return instance._client

    @classmethod
    def is_connected(cls) -> bool:
        """
        Check if MongoDB connection is active.

        Returns:
            True if connected, False otherwise
        """
        instance = cls()
        return instance._client is not None and instance._database is not None


# Global connection instance accessor
def get_mongo_database() -> AsyncIOMotorDatabase:
    """Helper function to get connected database."""
    return MongoConnection.get_database()


def get_mongo_client() -> AsyncIOMotorClient:
    """Helper function to get MongoDB client."""
    return MongoConnection.get_client()
