# Custom OpenCode Providers

This guide explains how to configure and use custom OpenCode providers with luskctl, such as local vLLM instances.

## Overview

luskctl supports custom OpenCode providers alongside the built-in Helmholtz Blablador provider. This allows you to use local LLM instances (like vLLM) with the same full-permission access as blablador.

## Setup

### 1. Configure the Custom Provider Path

Add the custom provider configuration to your `luskctl-config.yml`:

```yaml
# In ~/.config/luskctl/config.yml (or your global config location)
opencode:
  # Path to your custom OpenCode configuration file
  custom_config_path: "~/.config/luskctl/opencode-custom.json"
```

### 2. Create the OpenCode Configuration File

Create a JSON file at the specified path with your custom provider configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "local-llm/model-name",
  "provider": {
    "local-llm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Local LLM",
      "options": {
        "baseURL": "http://localhost:8000/v1/",
        "apiKey": "not-needed"
      },
      "models": {
        "model-name": {
          "name": "Local Model",
          "contextLength": 120000
        }
      }
    }
  },
  "permission": {
    "*": "allow"
  }
}
```

**Example Configuration:**
- See `examples/opencode-custom-example.json` for a complete example
- Replace `http://localhost:8000/v1/` with your local LLM API endpoint
- Replace `model-name` with your actual model identifier
- Adjust `contextLength` to match your model's capabilities

## Usage

### Starting OpenCode with Custom Provider

Once configured, simply run:

```bash
opencode-custom
```

This will:
1. Load your custom OpenCode configuration
2. Set up full permissions (same as blablador)
3. Launch OpenCode connected to your local LLM

### Available Commands

After logging into a luskctl container, you'll see the available agents:

```
Available AI agents:
  codex          - OpenAI Codex CLI (auto-approve enabled)
  claude         - Claude Code CLI (permissions skipped)
  vibe           - Mistral Vibe CLI (auto-approve enabled)
  blablador      - OpenCode with Helmholtz Blablador (full permissions)
  opencode-custom - OpenCode with custom local LLM (full permissions)
```

The `opencode-custom` option only appears when you have configured a custom provider.

## Configuration Options

### Multiple Models

You can configure multiple models in your provider:

```json
"models": {
  "model-1": {
    "name": "Fast Model",
    "contextLength": 8000
  },
  "model-2": {
    "name": "Large Model", 
    "contextLength": 120000
  }
}
```

### Authentication

If your local LLM requires authentication:

```json
"options": {
  "baseURL": "http://localhost:8000/v1/",
  "apiKey": "your-api-key-here"
}
```

### Provider Name

Customize the provider name that appears in OpenCode:

```json
"provider": {
  "my-custom-provider": {
    "name": "My Custom LLM",
    ...
  }
}
```

## Troubleshooting

### Configuration Not Found

If you get `No custom OpenCode config path specified`, ensure:
- You've added the `opencode.custom_config_path` to your `luskctl-config.yml`
- The path is correct and accessible
- The file exists at the specified location

### Invalid JSON

If you get `Failed to load custom OpenCode config`, check:
- Your JSON file is valid (use `jq` or a JSON validator)
- All required fields are present
- No trailing commas or syntax errors

### OpenCode Not Found

If you get `opencode not found`, you need to:
- Rebuild your L1 CLI image: `luskctl build <project> --build-all`
- Ensure the build completes successfully

## Comparison: Blablador vs Custom Provider

| Feature | Blablador | Custom Provider |
|---------|-----------|----------------|
| **Configuration** | Automatic (API-based) | Manual (JSON file) |
| **Models** | Fetched from API | Specified in config |
| **Permissions** | Full access | Full access |
| **Command** | `blablador` | `opencode-custom` |
| **Use Case** | Helmholtz Blablador | Local vLLM instances |

## Best Practices

1. **Start Simple**: Begin with a single model configuration
2. **Test Locally**: Verify your LLM API works before configuring in luskctl
3. **Use Descriptive Names**: Help identify your provider in OpenCode
4. **Set Appropriate Context Length**: Match your model's actual capabilities
5. **Keep Config Secure**: If using API keys, ensure proper file permissions

## Example Workflow

1. **Start your local LLM server** (e.g., vLLM):
   ```bash
   python -m vllm.entrypoints.openai.api_server --model your-model
   ```

2. **Configure luskctl**:
   ```bash
   echo 'opencode:
  custom_config_path: "~/.config/luskctl/opencode-custom.json"' >> ~/.config/luskctl/config.yml
   ```

3. **Create config file**:
   ```bash
   cp examples/opencode-custom-example.json ~/.config/luskctl/opencode-custom.json
   # Edit the file with your actual model and API details
   ```

4. **Use in luskctl container**:
   ```bash
   luskctl cli your-project
   # In container:
   opencode-custom
   ```

## Support

For issues with custom providers:
- Check your LLM server logs
- Verify the API endpoint is accessible from containers
- Ensure your OpenCode configuration is valid JSON
- Consult the [OpenCode documentation](https://opencode.ai/docs)

The custom provider feature gives you full flexibility to use any OpenAI-compatible LLM endpoint with luskctl's OpenCode integration.
