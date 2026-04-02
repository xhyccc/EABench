/// Data generation pipeline – LLM-based synthetic tenant data generation.
pub mod llm_provider;
pub mod models;
pub mod openai_provider;
pub mod pipeline;

pub use llm_provider::{LLMProvider, LLMResponse, Message, MockLLMProvider, ToolCall};
pub use models::{GenerationOutput, StoryConfig};
pub use openai_provider::{AzureOpenAIProvider, OpenAIProvider};
pub use pipeline::DataGenerator;
