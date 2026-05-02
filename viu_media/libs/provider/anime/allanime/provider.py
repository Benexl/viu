import logging
from json import dumps
from typing import Any, Iterator

from .....core.utils.graphql import execute_graphql
from ..base import BaseAnimeProvider
from ..params import AnimeParams, EpisodeStreamsParams, SearchParams
from ..types import Anime, SearchResults, Server
from ..utils.debug import debug_provider
from .constants import (
    ANIME_GQL,
    API_EPISODE_HEADERS,
    API_GRAPHQL_ENDPOINT,
    API_GRAPHQL_HEADERS,
    API_GRAPHQL_REFERER,
    EPISODE_GQL,
    PERSISTED_QUERY_SHA256,
    SEARCH_GQL,
    TOBEPARSED_DECRYPTION_SEED,
)
from .mappers import (
    map_to_anime_result,
    map_to_search_results,
)
from .types import AllAnimeEpisode
from .utils import decode_tobeparsed

logger = logging.getLogger(__name__)


class AllAnime(BaseAnimeProvider):
    HEADERS = {"Referer": API_GRAPHQL_REFERER}

    @debug_provider
    def search(self, params: SearchParams) -> SearchResults | None:
        response = execute_graphql(
            API_GRAPHQL_ENDPOINT,
            self.client,
            SEARCH_GQL,
            variables={
                "search": {
                    "allowAdult": params.allow_nsfw,
                    "allowUnknown": params.allow_unknown,
                    "query": params.query,
                },
                "limit": params.page_limit,
                "page": params.current_page,
                "translationType": params.translation_type,
                "countryOrigin": params.country_of_origin,
            },
            headers=API_GRAPHQL_HEADERS,
        )
        return map_to_search_results(response)

    @debug_provider
    def get(self, params: AnimeParams) -> Anime | None:
        response = execute_graphql(
            API_GRAPHQL_ENDPOINT,
            self.client,
            ANIME_GQL,
            variables={"showId": params.id},
            headers=API_GRAPHQL_HEADERS,
        )
        return map_to_anime_result(response)

    @debug_provider
    def episode_streams(self, params: EpisodeStreamsParams) -> Iterator[Server] | None:
        from .extractors import extract_server

        episode = self._get_episode_payload(params)
        if not episode:
            logger.error(
                f"Could not fetch streams for episode {params.episode} ({params.translation_type})"
            )
            return

        sources = episode.get("sourceUrls") or []
        if not sources:
            logger.error(
                f"No sources found for episode {params.episode} ({params.translation_type})"
            )
            return

        for source in sources:
            if server := extract_server(self.client, params.episode, episode, source):
                yield server

    def _extract_episode_from_payload(self, payload: dict[str, Any]) -> AllAnimeEpisode | None:
        data = payload.get("data")
        if not isinstance(data, dict):
            return None

        episode = data.get("episode")
        if isinstance(episode, dict):
            return episode  # type: ignore[return-value]

        encoded_payload = data.get("tobeparsed")
        if not isinstance(encoded_payload, str):
            return None

        parsed_payload = decode_tobeparsed(encoded_payload, TOBEPARSED_DECRYPTION_SEED)
        parsed_episode = parsed_payload.get("episode")
        if isinstance(parsed_episode, dict):
            return parsed_episode  # type: ignore[return-value]
        return None

    def _get_episode_payload(self, params: EpisodeStreamsParams) -> AllAnimeEpisode | None:
        persisted_query_response = self.client.get(
            API_GRAPHQL_ENDPOINT,
            params={
                "variables": dumps(
                    {
                        "showId": params.anime_id,
                        "translationType": params.translation_type,
                        "episodeString": params.episode,
                    },
                    separators=(",", ":"),
                ),
                "extensions": dumps(
                    {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": PERSISTED_QUERY_SHA256,
                        }
                    },
                    separators=(",", ":"),
                ),
            },
            headers={**API_GRAPHQL_HEADERS, **API_EPISODE_HEADERS},
        )
        persisted_query_response.raise_for_status()

        if episode := self._extract_episode_from_payload(persisted_query_response.json()):
            return episode

        episode_response = execute_graphql(
            API_GRAPHQL_ENDPOINT,
            self.client,
            EPISODE_GQL,
            variables={
                "showId": params.anime_id,
                "translationType": params.translation_type,
                "episodeString": params.episode,
            },
            headers=API_GRAPHQL_HEADERS,
        )
        return self._extract_episode_from_payload(episode_response.json())


if __name__ == "__main__":
    from ..utils.debug import test_anime_provider

    test_anime_provider(AllAnime)
