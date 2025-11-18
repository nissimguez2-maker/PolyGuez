<!-- d6491107-1dc2-492d-be7f-b86c981c8e3e 89d7d492-1c73-49a3-8f4e-244df2a954bb -->
# Add Multi-Provider Search and OpenRouter LLM Support

## Changes to `agents/connectors/search.py`

Refactor to support multiple search providers (Tavily, Exa, Kagi, Perplexity):

- Create a `SearchProvider` class/interface that normalizes search results
- Implement provider-specific classes: `TavilySearch`, `ExaSearch`, `KagiSearch`, `PerplexitySearch`
- Use `SEARCH_PROVIDER` env var (defaults to "tavily") to select provider
- Add env vars: `EXA_API_KEY`, `KAGI_API_KEY`, `PERPLEXITY_API_KEY`
- Maintain similar interface: `get_search_context(query: str)` returning context string

## Changes to `agents/application/executor.py`

Add OpenRouter support for LLM:

- Check `LLM_PROVIDER` env var (defaults to "openai")
- When `LLM_PROVIDER=openrouter`, configure `ChatOpenAI` with:
- `base_url="https://openrouter.ai/api/v1"`
- `api_key` from `OPENROUTER_API_KEY` env var
- Support `LLM_MODEL` env var for model selection (defaults to current model)
- Keep existing OpenAI behavior as default

## Changes to `.env.example`

Add new environment variables:

- `SEARCH_PROVIDER=tavily` (options: tavily, exa, kagi, perplexity)
- `EXA_API_KEY=`
- `KAGI_API_KEY=`
- `PERPLEXITY_API_KEY=`
- `LLM_PROVIDER=openai` (options: openai, openrouter)
- `OPENROUTER_API_KEY=`
- `LLM_MODEL=gpt-3.5-turbo-16k` (for OpenRouter model selection)

## Dependencies

Add required packages to `requirements.txt`:

- `exa-py` or appropriate Exa SDK
- `kagi` or appropriate Kagi SDK  
- `perplexity` or appropriate Perplexity SDK

### To-dos

- [ ] Refactor search.py to support multiple providers (Tavily, Exa, Kagi, Perplexity) with provider selection via env var
- [ ] Modify executor.py to support OpenRouter LLM provider with custom endpoint configuration
- [ ] Create/update .env.example with all new API keys and configuration environment variables
- [ ] Add required Python packages for Exa, Kagi, and Perplexity APIs to requirements.txt