const { Configuration, OpenAIApi } = require("openai");
const fs = require("fs");

const configuration = new Configuration({
  apiKey: "YOUR_OPENAI_API_KEY",
});
const openai = new OpenAIApi(configuration);

async function generatePost(topic) {
  const res = await openai.createChatCompletion({
    model: "gpt-3.5-turbo",
    messages: [{ role: "user", content: `Write a markdown blog about: ${topic}` }],
  });

  const content = res.data.choices[0].message.content;
  fs.writeFileSync(`_posts/${topic.replace(/ /g, "_")}.md`, content);
}

generatePost("How AI is Changing Blogging");
