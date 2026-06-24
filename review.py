#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识复习系统 — 基于 Markdown 标题层级的交互式复习工具

规则：
  - 一级标题（#）→ 题目
  - 二级标题（##）→ 答案（复习者需要回答的内容）
  - 三级及更深标题（###, ####...）→ 详细内容的一部分
  - 模糊匹配（difflib），阈值 0.5
  - 每个答案最多 3 次错误机会，超限后公布答案
  - 复习结束后记录到 review_log.json
"""

import os
import sys
import re
import json
import difflib
from datetime import date
from collections import OrderedDict

# 强制 stdout 使用 UTF-8 编码（解决 Windows GBK 下 emoji 报错）
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ============================================================================
# 1. MarkdownParser — 解析 md 文件
# ============================================================================

def strip_markdown_format(text: str) -> str:
    """去除 Markdown 内联格式标记（**bold**, *italic*, `code` 等）"""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)         # *italic*
    text = re.sub(r'__(.+?)__', r'\1', text)         # __bold__
    text = re.sub(r'_(.+?)_', r'\1', text)           # _italic_
    text = re.sub(r'`(.+?)`', r'\1', text)           # `code`
    text = re.sub(r'~~(.+?)~~', r'\1', text)         # ~~strikethrough~~
    return text.strip()


def is_date_line(line: str) -> bool:
    """判断一行是否是纯日期行（如 '6月22日'、'2026-06-22'）"""
    line = line.strip()
    if not line:
        return False
    # 匹配中文日期：6月22日、06月22日
    if re.match(r'^\d{1,2}月\d{1,2}日$', line):
        return True
    # 匹配 ISO 日期：2026-06-22
    if re.match(r'^\d{4}-\d{2}-\d{2}$', line):
        return True
    return False


def parse_markdown(filepath: str) -> OrderedDict:
    """
    解析知识笔记 md 文件。

    返回: OrderedDict，key 为一级标题文本，value 为 [(二级标题文本, 详细内容), ...]

    特殊处理：
      - 跳过纯日期行
      - 如果一级标题本身是日期（如 "# 6月22日"），跳过它，
        用文件名（去扩展名）作为主题名
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 从文件路径提取文件名（去扩展名）作为备用主题
    basename = os.path.basename(filepath)
    fallback_topic = os.path.splitext(basename)[0]

    result = OrderedDict()
    current_h1 = None          # 当前一级标题
    current_h2 = None          # 当前二级标题
    current_content = []       # 当前二级标题下的内容行
    subtopics = []             # 当前一级标题下的所有 (h2, content) 对
    h1_is_date = False         # 当前一级标题是否是日期

    def flush_h1():
        """将当前缓存的一级标题及其子标题写入结果"""
        nonlocal current_h1, current_h2, current_content, subtopics, h1_is_date
        if current_h2 is not None:
            subtopics.append((current_h2, '\n'.join(current_content).strip()))
            current_h2 = None
            current_content = []
        if subtopics:
            topic = current_h1 if current_h1 and not h1_is_date else fallback_topic
            # 如果该 topic 已存在，合并到已有条目
            if topic in result:
                result[topic].extend(subtopics)
            else:
                result[topic] = subtopics
        current_h1 = None
        subtopics = []
        h1_is_date = False

    for line in lines:
        stripped = line.rstrip()

        # 跳过纯日期行（非标题行）
        if is_date_line(stripped):
            continue

        # 一级标题
        if stripped.startswith('# ') and not stripped.startswith('## '):
            h1_text = strip_markdown_format(stripped[2:])
            # 检查一级标题是否看起来像日期
            if is_date_line(h1_text):
                flush_h1()  # 保存之前的内容
                # 将日期作为"隐形" H1：后面的 H2 归入 fallback_topic
                current_h1 = h1_text
                h1_is_date = True
                subtopics = []
                current_h2 = None
                current_content = []
            else:
                flush_h1()  # 保存之前的内容
                current_h1 = h1_text
                h1_is_date = False
                subtopics = []
                current_h2 = None
                current_content = []

        # 二级标题
        elif stripped.startswith('## ') and not stripped.startswith('### '):
            # 保存上一个 h2 的内容
            if current_h2 is not None:
                subtopics.append((current_h2, '\n'.join(current_content).strip()))

            current_h2 = strip_markdown_format(stripped[3:])
            current_content = []

        # 三级及更深标题、或普通内容 → 追加到当前 h2 的内容
        else:
            if current_h2 is not None:
                current_content.append(stripped)
            elif current_h1 is not None and stripped.strip():
                # 一级标题下、二级标题前的内容（导语/说明）
                pass  # 目前不保留，可以作为题干的补充说明

    # 保存最后一个 h1 的内容
    flush_h1()

    return result


# ============================================================================
# 2. FuzzyMatcher — 模糊匹配
# ============================================================================

def fuzzy_match(user_input: str, target: str) -> float:
    """
    计算用户输入与目标答案的相似度。

    参数:
        user_input: 用户输入的答案
        target: 二级标题（正确答案）

    返回: 0.0 ~ 1.0 的相似度
    """
    a = user_input.strip().lower()
    b = target.strip().lower()

    # 去除常见标点符号（中文 + 英文）
    punctuation = '，。！？、；：""''（）【】《》…—·,.;:!?"\'()[]{}@#$%^&*+=<>'
    for p in punctuation:
        a = a.replace(p, '')
        b = b.replace(p, '')

    if not a or not b:
        return 0.0

    # 完全匹配直接返回 1.0
    if a == b:
        return 1.0

    # 子串包含（用户答案包含正确答案 或 正确答案包含用户答案）
    if a in b or b in a:
        # 短文本子串匹配给高分
        return 0.85

    # difflib 序列匹配
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio


# ============================================================================
# 3. ReviewSession — 交互式复习会话
# ============================================================================

MAX_WRONG_ATTEMPTS = 3
MATCH_THRESHOLD = 0.5


def print_separator(char='=', length=50):
    print(char * length)


def print_content_box(content: str):
    """以美观的框展示详细内容"""
    if not content:
        print("   (无详细内容)")
        return
    print_separator('-', 50)
    # 对内容的每一行添加缩进
    for line in content.split('\n'):
        print(f"   {line}")
    print_separator('-', 50)


class ReviewSession:
    """管理一个知识主题的复习会话"""

    def __init__(self, topic: str, subtopics: list):
        """
        参数:
            topic: 一级标题（题目）
            subtopics: [(二级标题, 详细内容), ...]
        """
        self.topic = topic
        self.subtopics = subtopics
        self.results = []  # [(subtopic, is_correct, attempts), ...]

    def run(self) -> list:
        """运行复习会话，返回结果列表"""
        total = len(self.subtopics)

        print(f"\n📝 题目: {self.topic} 包含哪些知识点？")
        print(f"   （共 {total} 个知识点需要回答）\n")

        for i, (subtopic, content) in enumerate(self.subtopics, 1):
            attempts = 0
            is_correct = False

            while attempts < MAX_WRONG_ATTEMPTS:
                attempts += 1
                prompt = f"🔍 第 {i}/{total} 个知识点，请回答: "
                try:
                    user_answer = input(prompt).strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n\n⚠️ 复习被中断。")
                    # 将当前未完成的题目记为错误
                    if not is_correct:
                        self.results.append((subtopic, False, attempts))
                    return self.results

                if not user_answer:
                    print("   ⚠️ 请输入答案，不要留空。")
                    attempts -= 1  # 空输入不计次数
                    continue

                similarity = fuzzy_match(user_answer, subtopic)

                if similarity >= MATCH_THRESHOLD:
                    print(f"   ✅ 正确！（相似度: {similarity:.0%}）")
                    is_correct = True
                    break
                else:
                    remaining = MAX_WRONG_ATTEMPTS - attempts
                    if remaining > 0:
                        print(f"   ❌ 不匹配（相似度: {similarity:.0%}），"
                              f"还剩 {remaining} 次机会，请重试。")
                    # 给出提示：显示正确答案的第一个字作为线索
                    if remaining == 1 and len(subtopic) > 0:
                        hint_char = subtopic[0]
                        print(f"   💡 提示：正确答案以「{hint_char}」开头")

            if is_correct:
                print(f"   📄 详细内容：")
                print_content_box(content)
            else:
                # 3 次错误，公布答案
                print(f"\n   ❌ 3 次错误！正确答案是: {subtopic}")
                print(f"   📄 详细内容：")
                print_content_box(content)

            self.results.append((subtopic, is_correct, attempts))
            print()  # 题目之间空行

        return self.results


# ============================================================================
# 4. ReviewRecorder — 复习记录
# ============================================================================

LOG_FILE = "review_log.json"


def load_records() -> dict:
    """加载已有复习记录"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"records": []}
    return {"records": []}


def save_record(file_name: str, session_results: list):
    """
    保存一次复习记录。

    参数:
        file_name: 复习的知识文件名称
        session_results: [(topic, [(subtopic, is_correct, attempts), ...]), ...]
    """
    data = load_records()
    today = date.today().isoformat()

    # 构建记录
    all_details = []
    total_correct = 0
    total_questions = 0

    for topic, subtopic_results in session_results:
        for subtopic, is_correct, attempts in subtopic_results:
            total_questions += 1
            if is_correct:
                total_correct += 1
            all_details.append({
                "topic": topic,
                "subtopic": subtopic,
                "correct": is_correct,
                "attempts": attempts
            })

    record = {
        "date": today,
        "file": file_name,
        "total_questions": total_questions,
        "correct": total_correct,
        "wrong": total_questions - total_correct,
        "score": f"{total_correct}/{total_questions}",
        "percentage": round(total_correct / total_questions * 100, 1) if total_questions > 0 else 0,
        "details": all_details
    }

    data["records"].append(record)

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n📊 复习结果已保存到 {LOG_FILE}")


# ============================================================================
# 5. main — 入口
# ============================================================================

def discover_knowledge_files(directory: str = ".") -> list:
    """
    发现目录下的知识笔记 md 文件。
    排除：README.md、复习计划.md、以及 review 相关的文件
    """
    exclude = {"README.md", "复习计划.md", "readme.md"}
    knowledge_files = []

    for f in os.listdir(directory):
        if f.endswith('.md') and f not in exclude and not f.startswith('review'):
            filepath = os.path.join(directory, f)
            # 验证文件包含有效的一级标题
            parsed = parse_markdown(filepath)
            if parsed:
                knowledge_files.append(f)

    return sorted(knowledge_files)


def print_header():
    """打印系统标题"""
    print()
    print_separator('=', 50)
    print("  📚 知识复习系统  |  Based on Markdown Headings")
    print_separator('=', 50)


def review_file(file_name: str) -> list:
    """
    复习单个文件，返回 [(topic, [(subtopic, is_correct, attempts), ...]), ...]
    """
    filepath = file_name
    if not os.path.isabs(file_name):
        filepath = os.path.join(os.getcwd(), file_name)

    parsed = parse_markdown(filepath)

    if not parsed:
        print(f"⚠️ 文件 {file_name} 中没有找到有效的一级标题和二级标题。")
        return []

    print(f"\n📖 正在复习: {file_name}")
    print_separator('=', 50)
    print(f"   共 {len(parsed)} 个大题\n")

    all_results = []

    for topic, subtopics in parsed.items():
        if not subtopics:
            print(f"⚠️ 主题「{topic}」下没有二级标题，跳过。\n")
            continue
        session = ReviewSession(topic, subtopics)
        results = session.run()
        all_results.append((topic, results))

    return all_results


def show_summary(all_results: list):
    """显示复习总结"""
    total_correct = 0
    total_questions = 0

    for _, subtopic_results in all_results:
        for _, is_correct, _ in subtopic_results:
            total_questions += 1
            if is_correct:
                total_correct += 1

    print_separator('=', 50)
    print("📊 复习完成！")
    print(f"   正确: {total_correct}/{total_questions}")
    if total_questions > 0:
        pct = total_correct / total_questions * 100
        stars = '⭐' * int(pct / 20) if pct > 0 else ''
        print(f"   得分: {pct:.1f}% {stars}")
    print_separator('=', 50)


def main():
    print_header()

    # 发现知识文件
    knowledge_files = discover_knowledge_files()
    if not knowledge_files:
        print("\n❌ 没有找到可复习的知识笔记文件。")
        print("   请确保目录下有包含 # 一级标题和 ## 二级标题的 .md 文件。")
        return

    # 显示菜单
    print("\n📂 可复习的知识主题：")
    for i, f in enumerate(knowledge_files, 1):
        # 统计题目数
        parsed = parse_markdown(f)
        h1_count = len(parsed)
        h2_count = sum(len(v) for v in parsed.values())
        print(f"  {i}. {f}  ({h1_count} 个主题, {h2_count} 个知识点)")
    print(f"  0. 全部复习 ({len(knowledge_files)} 个文件)")
    print(f"  q. 退出")

    try:
        choice = input(f"\n请选择 (0-{len(knowledge_files)}): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n👋 再见！")
        return

    if choice.lower() == 'q':
        print("👋 再见！")
        return

    # 解析选择
    if choice == '0':
        selected_files = knowledge_files
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(knowledge_files):
                selected_files = [knowledge_files[idx]]
            else:
                print(f"❌ 无效选择: {choice}")
                return
        except ValueError:
            print(f"❌ 无效输入: {choice}")
            return

    # 逐个复习
    all_results_for_log = []

    for f in selected_files:
        results = review_file(f)
        if results:
            all_results_for_log.append((f, results))

    # 显示总结
    if all_results_for_log:
        # 汇总所有文件的复习结果
        flat_results = []
        for _, results in all_results_for_log:
            flat_results.extend(results)
        show_summary(flat_results)

        # 保存记录
        for f, results in all_results_for_log:
            save_record(f, results)

        print("\n💡 提示：可以使用 `python review.py` 再次复习。")
    else:
        print("\n⚠️ 没有完成任何复习。")


if __name__ == '__main__':
    main()
