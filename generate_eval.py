import asyncio
import argparse
import os
import yaml
from dotenv import load_dotenv
from src.core.openai_provider import OpenAIProvider
from src.core.azure_provider import AzureOpenAIProvider
from src.generator.pipeline import DataGenerator

async def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Generate evaluation dataset for an existing tenant")
    parser.add_argument("--tenant_path", type=str, required=True, help="Path to the tenant directory (e.g., examples/tenants/technova-20251230)")
    parser.add_argument("--num_queries", type=int, default=200, help="Number of queries to generate")
    parser.add_argument("--batch_size", type=int, default=10, help="Batch size for search query generation")
    parser.add_argument("--prompts", type=str, default="examples/generation/default_prompts.yaml", help="Path to prompts config file")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.tenant_path):
        print(f"Error: Tenant path {args.tenant_path} does not exist.")
        return

    # Load prompts config to get model settings
    if not os.path.exists(args.prompts):
        print(f"Error: Prompts file not found at {args.prompts}")
        return

    with open(args.prompts, "r") as f:
        prompts_config = yaml.safe_load(f)
    
    model_config = prompts_config.get("model_config", {})
    provider = model_config.get("provider", "openai")
    model_name = model_config.get("model")

    # Initialize LLM
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY not found in environment variables.")
            return

        llm = OpenAIProvider(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE"),
            model=model_name or os.getenv("OPENAI_MODEL", "gpt-4o")
        )
    else:
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_ENDPOINT")
        deployment = model_name or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_DEPLOYMENT_NAME")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("AZURE_API_VERSION") or "2023-05-15"

        if not api_key or not endpoint:
            print("Error: AZURE_OPENAI_API_KEY (or AZURE_API_KEY) and AZURE_OPENAI_ENDPOINT (or AZURE_ENDPOINT) are required.")
            return
        
        if not deployment:
             print("Error: AZURE_OPENAI_DEPLOYMENT_NAME (or AZURE_DEPLOYMENT_NAME) is missing in .env and not specified in prompts yaml.")
             return

        llm = AzureOpenAIProvider(
            api_key=api_key,
            azure_endpoint=endpoint,
            deployment_name=deployment,
            api_version=api_version
        )

    generator = DataGenerator(llm=llm, prompts_path=args.prompts)
    
    tenant_id = os.path.basename(args.tenant_path)
    base_path = args.tenant_path
    
    await generator.generate_eval_dataset(tenant_id, base_path, num_queries=args.num_queries, batch_size=args.batch_size)

if __name__ == "__main__":
    asyncio.run(main())
