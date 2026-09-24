import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WeChatChatPage } from "./WeChatChatPage";
import type { ApiClient } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function makeClient() {
  return {
    wechatMe: vi.fn().mockResolvedValue({ id: "wx_test" }),
    wechatConversations: vi.fn().mockResolvedValue([]),
    wechatMemories: vi.fn().mockResolvedValue([{ key: "goal", value: "准备面试", evidence: "我的目标是准备面试" }]),
    wechatRecommendations: vi.fn().mockResolvedValue([{ id: "a1", title: "Go 实践", url: "https://example.org/go", reason: "目标匹配", score: 1 }]),
    wechatSend: vi.fn().mockResolvedValue({ id: 1 }),
    wechatForget: vi.fn().mockResolvedValue(undefined)
  };
}

describe("WeChatChatPage", () => {
  it("sends a message and exposes recommendation links", async () => {
    const api = makeClient(); const user = userEvent.setup();
    vi.stubGlobal("crypto", {
      getRandomValues(bytes: Uint8Array) {
        bytes.fill(0x22);
        return bytes;
      }
    });
    render(<WeChatChatPage client={api as unknown as ApiClient} />);
    await user.type(await screen.findByRole("textbox", { name: "输入消息" }), "请推荐");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(api.wechatSend).toHaveBeenCalledWith(expect.objectContaining({
      request_id: "22222222-2222-4222-a222-222222222222",
      text: "请推荐"
    }));
    expect(screen.getByRole("link", { name: /Go 实践/ })).toHaveAttribute("href", "https://example.org/go");
  });
  it("deletes a memory for the signed-in user", async () => {
    const api = makeClient(); const user = userEvent.setup();
    render(<WeChatChatPage client={api as unknown as ApiClient} />);
    await user.click(await screen.findByRole("button", { name: "删除目标" }));
    expect(api.wechatForget).toHaveBeenCalledWith("goal");
  });
  it("shows a network error when sending fails", async () => {
    const api = makeClient();
    api.wechatSend.mockRejectedValue(new Error("网络暂时不可用"));
    const user = userEvent.setup();
    render(<WeChatChatPage client={api as unknown as ApiClient} />);
    await user.type(await screen.findByRole("textbox", { name: "输入消息" }), "你好");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("网络暂时不可用");
  });

  it("keeps the chat open when only the memory service is unavailable", async () => {
    const api = makeClient();
    api.wechatMemories.mockRejectedValue(Object.assign(new Error("记忆暂时不可用"), { status: 503 }));
    render(<WeChatChatPage client={api as unknown as ApiClient} />);

    expect(await screen.findByRole("heading", { name: "KnowMate" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "输入消息" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("记忆暂时不可用");
    expect(screen.queryByRole("heading", { name: "需要微信授权" })).not.toBeInTheDocument();
  });
});
