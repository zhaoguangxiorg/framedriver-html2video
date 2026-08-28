// 选项卡切换与历史加载
(function () {
  window.onSessionSelected = async function (s) {
    // 清理上一个会话的轮询状态与界面，防止泄漏到新会话
    // （执行态由 _cleanupAgentState 清理，界面态清空为 empty-hint，随后加载历史消息时会覆盖）
    clearAllState();

    // 并行加载 content 消息、ppt 消息、幻灯片卡片
    const [contentMsgs, pptMsgs, slides] = await Promise.all([
      api("GET", `/api/messages/${s.project_id}?tab=content`).catch(() => []),
      api("GET", `/api/messages/${s.project_id}?tab=ppt`).catch(() => []),
      api("GET", `/api/slides/${s.project_id}`).catch(() => []),
    ]);

    // 渲染 content 历史消息
    if (contentMsgs && contentMsgs.length) {
      contentMsgs.forEach((m) => {
        window.appendMessage && window.appendMessage(
          $("#chatContainer"),
          m.role,
          m.content,
          { steps: m.steps, status: m.status },
        );
      });
      // 加载内容卡片（如果有 content.md）
      await window.appendContentCard && window.appendContentCard($("#chatContainer"));
    } else {
      $("#chatContainer").innerHTML = '<div class="empty-hint">会话已选择，开始对话吧</div>';
    }

    // 建 slide_index → 最新 slide 数据的映射，补全旧记录缺失的 slide_text/narration
    const slideMap = {};
    if (slides && slides.length) {
      slides.forEach(s => { slideMap[s.slide_index] = s; });
    }

    // 找到最后一条 pending 的 agent 消息
    var lastPendingId = null;
    for (var pi = pptMsgs.length - 1; pi >= 0; pi--) {
      if (pptMsgs[pi].role === "agent" && pptMsgs[pi].status === "pending") {
        lastPendingId = pptMsgs[pi].id;
        break;
      }
    }

    // 找到最后一条 agent 消息（用于步骤标题状态展示）
    var lastAgentId = null;
    for (var ai = pptMsgs.length - 1; ai >= 0; ai--) {
      if (pptMsgs[ai].role === "agent") {
        lastAgentId = pptMsgs[ai].id;
        break;
      }
    }

    // 渲染 ppt 历史消息
    if (pptMsgs && pptMsgs.length) {
      pptMsgs.forEach((m) => {
        // 兼容老数据：若有 slides 字段但无 cards，补全 slides 的最新字段
        if (m.slides && m.slides.length) {
          m.slides.forEach(sl => {
            const latest = slideMap[sl.slide_index];
            if (latest) {
              if (!sl.slide_text) sl.slide_text = latest.slide_text;
              if (!sl.narration) sl.narration = latest.narration;
              sl.html_path = latest.html_path;  // 总是覆盖为最新地址（避免旧地址404）
            }
          });
        }
        // 新结构：cards 数组中可能含 slides 卡片，也需补全最新字段
        if (m.cards && m.cards.length) {
          m.cards.forEach(c => {
            if (c.card_type === "slides" && c.card_data) {
              const latest = slideMap[c.card_data.slide_index];
              if (latest) {
                if (!c.card_data.slide_text) c.card_data.slide_text = latest.slide_text;
                if (!c.card_data.narration) c.card_data.narration = latest.narration;
                c.card_data.html_path = latest.html_path;
              }
            }
          });
        }
        if (m.role === "agent" && m.status === "pending") {
          if (m.id !== lastPendingId) {
            // 不是最后一条 pending → 标为执行异常
            window.appendMessage && window.appendMessage(
              $("#pptChatContainer"),
              "agent",
              "❌ 智能体执行异常，请重新发送",
              { steps: m.steps, slides: m.slides, cards: m.cards, allSlides: slides, status: "error" },
            );
          }
          // 最后一条 pending 跳过渲染（由 _checkPendingAfterLoad 处理）
        } else {
          window.appendMessage && window.appendMessage(
            $("#pptChatContainer"),
            m.role,
            m.content,
            { steps: m.steps, slides: m.slides, cards: m.cards, allSlides: slides, status: m.status, isLastAgent: m.id === lastAgentId },
          );
        }
      });
      // 有幻灯片时显示画廊按钮（兼容 cards 新结构与 slides 老数据）
      const hasSlides = pptMsgs.some((m) =>
        (m.cards && m.cards.some(c => c.card_type === "slides")) ||
        (m.slides && m.slides.length > 0)
      );
      const btn = $("#galleryBtn");
      if (btn) btn.hidden = !hasSlides;
    } else {
      const btn = $("#galleryBtn");
      if (btn) btn.hidden = true;
    }

    if (!pptMsgs.length) {
      if (!$("#pptChatContainer").innerHTML) {
        $("#pptChatContainer").innerHTML = '<div class="empty-hint">已选择会话</div>';
      }
    }

    // 最后一条 pending 消息的状态检查（直接调用，不依赖 setTimeout）
    if (lastPendingId && window._checkPendingAfterLoad) {
      window._checkPendingAfterLoad();
    }

    // 历史消息渲染完成后，自动滚动到聊天区底部，直接看到最新消息
    $("#chatContainer").scrollTop = $("#chatContainer").scrollHeight;
    $("#pptChatContainer").scrollTop = $("#pptChatContainer").scrollHeight;
  };
})();
