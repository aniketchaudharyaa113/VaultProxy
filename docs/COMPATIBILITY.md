# VaultProxy Multi-Language Integration Guide

VaultProxy is an OpenAI-compatible HTTP reverse proxy. Any programming language, framework, or client library that can communicate with the OpenAI API can use VaultProxy with **zero modifications** to prompt engineering or schema logic.

Simply change the **`base_url`** (or `baseURL`) to `http://127.0.0.1:8000/v1` (or `http://127.0.0.1:8000`).

---

## 1. Node.js & TypeScript

### Using the Official OpenAI SDK (`openai` npm package)

```typescript
import OpenAI from "openai";

const openai = new OpenAI({
  baseURL: "http://127.0.0.1:8000/v1", // or http://127.0.0.1:8000
  apiKey: process.env.VAULT_AUTH_TOKEN || "local_dev_token",
});

async function main() {
  const completion = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [
      { role: "user", content: "Customer PAN is ABCPB1234F and mobile is 9876543210." }
    ],
    stream: true,
  });

  for await (const chunk of completion) {
    process.stdout.write(chunk.choices[0]?.delta?.content || "");
  }
}

main();
```

### Using Native `fetch` (Node.js 18+)

```javascript
const response = await fetch("http://127.0.0.1:8000/v1/chat/completions", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${process.env.VAULT_AUTH_TOKEN || ""}`,
  },
  body: JSON.stringify({
    model: "gpt-4o",
    messages: [{ role: "user", content: "My Aadhaar is 367598341203" }],
  }),
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

---

## 2. Java & Spring Boot

### Option A: Spring AI

In your `application.yml` (or `application.properties`):

```yaml
spring:
  ai:
    openai:
      base-url: http://localhost:8000
      api-key: ${VAULT_AUTH_TOKEN:dummy_token}
      chat:
        options:
          model: gpt-4o
```

In your Spring Service:

```java
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.stereotype.Service;

@Service
public class AssistantService {

    private final ChatModel chatModel;

    public AssistantService(ChatModel chatModel) {
        this.chatModel = chatModel;
    }

    public String ask(String userPrompt) {
        // VaultProxy automatically masks PAN/Aadhaar/Phone before sending upstream,
        // and restores the real values in the returned reply.
        return chatModel.call(userPrompt);
    }
}
```

### Option B: LangChain4j

```java
import dev.langchain4j.model.openai.OpenAiChatModel;

OpenAiChatModel model = OpenAiChatModel.builder()
    .baseUrl("http://127.0.0.1:8000/v1")
    .apiKey(System.getenv().getOrDefault("VAULT_AUTH_TOKEN", "local_token"))
    .modelName("gpt-4o")
    .build();

String answer = model.generate("Customer PAN is ABCPB1234F");
System.out.println(answer);
```

---

## 3. Ruby

### Using `ruby-openai` Gem

```ruby
require "openai"

client = OpenAI::Client.new(
  access_token: ENV.fetch("VAULT_AUTH_TOKEN", "dummy_token"),
  uri_base: "http://127.0.0.1:8000"
)

response = client.chat(
  parameters: {
    model: "gpt-4o",
    messages: [
      { role: "user", content: "Verify account for Aadhaar 367598341203" }
    ]
  }
)

puts response.dig("choices", 0, "message", "content")
```

---

## 4. Go

### Using `github.com/sashabaranov/go-openai`

```go
package main

import (
	"context"
	"fmt"
	"os"

	openai "github.com/sashabaranov/go-openai"
)

func main() {
	config := openai.DefaultConfig(os.Getenv("VAULT_AUTH_TOKEN"))
	config.BaseURL = "http://127.0.0.1:8000/v1"

	client := openai.NewClientWithConfig(config)
	resp, err := client.CreateChatCompletion(
		context.Background(),
		openai.ChatCompletionRequest{
			Model: openai.GPT4o,
			Messages: []openai.ChatCompletionMessage{
				{
					Role:    openai.ChatMessageRoleUser,
					Content: "My PAN number is ABCPB1234F",
				},
			},
		},
	)
	if err != nil {
		panic(err)
	}

	fmt.Println(resp.Choices[0].Message.Content)
}
```

---

## 5. Python

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your_vault_auth_token",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "My PAN is ABCPB1234F"}],
    stream=True,
)

for chunk in response:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
```

### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your_vault_auth_token",
    model="gpt-4o",
)

print(llm.invoke("Customer phone is 9876543210").content)
```

---

## Summary of Compatible Routes

VaultProxy handles requests with or without the `/v1` prefix:

| Endpoint | Method | Supported Headers |
| :--- | :--- | :--- |
| `/v1/chat/completions` or `/chat/completions` | POST | `Authorization`, `Content-Type: application/json` |
| `/v1/embeddings` or `/embeddings` | POST | `Authorization`, `Content-Type: application/json` |
| `/v1/models` or `/models` | GET | `Authorization` |
| `/healthz` | GET | None (Health probe) |
| `/readyz` | GET | `Authorization` (optional in dev, diagnostic in prod) |
