import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "./api";
import { ChatPage } from "./ChatPage";

function client() {
  return { chatMessages: vi.fn().mockResolvedValue([]), chatMemories: vi.fn().mockResolvedValue([]),
    chatUsers: vi.fn().mockResolvedValue(["default-user", "wx_test"]),
    wechatStatus: vi.fn().mockResolvedValue({ enabled: false }), sendChat: vi.fn().mockResolvedValue({ id: 1 }),
    forgetChatMemory: vi.fn().mockResolvedValue({}) };
}

describe("chat", () => {
  it("sends a message without memory when the user opts out", async () => {
    const api = client(); const user = userEvent.setup();
    render(<ChatPage client={api as unknown as ApiClient} />);
    await screen.findByText("你好，我是你的知识助手");
    await user.click(screen.getByRole("checkbox"));
    await user.type(screen.getByRole("textbox", { name: "发送给知识助手的消息" }), "我想学习 Go");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(api.sendChat).toHaveBeenCalledWith(expect.objectContaining({ user_id: "default-user", text: "我想学习 Go", remember: false }));
  });
  it("reuses idempotency key when retrying a lost submission response", async () => {
    const api = client(); api.sendChat.mockRejectedValueOnce(new Error("network error"));
    const user = userEvent.setup(); render(<ChatPage client={api as unknown as ApiClient} />);
    await user.type(screen.getByRole("textbox", { name: "发送给知识助手的消息" }), "你好");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(2));
    expect(api.sendChat.mock.calls[0][0].request_id).toBe(api.sendChat.mock.calls[1][0].request_id);
    expect(api.sendChat.mock.calls[1][0].remember).toBe(api.sendChat.mock.calls[0][0].remember);
  });
  it("deletes only the selected user's memory", async () => {
    const api = client(); api.chatMemories.mockResolvedValue([{ key: "interests", value: "Go", evidence: "我喜欢 Go" }]);
    const user = userEvent.setup();render(<ChatPage client={api as unknown as ApiClient} />);
    await user.selectOptions(await screen.findByRole("combobox"), "wx_test");
    await user.click(await screen.findByRole("button", { name: "删除兴趣方向" }));
    expect(api.forgetChatMemory).toHaveBeenCalledWith("wx_test", "interests");
  });
});
