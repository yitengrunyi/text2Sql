from typing import Optional, Any

import aiohttp


async def post(url, data, headers=None):
    async with aiohttp.ClientSession(headers=headers) as session:
        result = await session.post(url, data=data)
        return await result.json()


SIZE_POOL_AIOHTTP = 100


class SingletonAiohttp:
    def __init__(self):
        pass

    aiohttp_client: Optional[aiohttp.ClientSession] = None

    @classmethod
    def get_aiohttp_client(cls) -> aiohttp.ClientSession:
        if cls.aiohttp_client is None:
            timeout = aiohttp.ClientTimeout(total=10)
            connector = aiohttp.TCPConnector(limit_per_host=SIZE_POOL_AIOHTTP)
            cls.aiohttp_client = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return cls.aiohttp_client

    @classmethod
    async def close_aiohttp_client(cls) -> None:
        if cls.aiohttp_client:
            await cls.aiohttp_client.close()
            cls.aiohttp_client = None

    @classmethod
    async def query_url(cls, url: str) -> Any:
        client = cls.get_aiohttp_client()

        try:
            async with client.post(url) as response:
                if response.status != 200:
                    return {"ERROR OCCURED" + str(await response.text())}

                json_result = await response.json()
        except Exception as e:
            return {"ERROR": e}

        return json_result
