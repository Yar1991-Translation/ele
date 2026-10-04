"""prompt 模板加载。模板里用 $变量 占位（string.Template，JSON 花括号不用转义）。"""
import os
from string import Template

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")
SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

_SKILL_CACHE = {}


def load_prompt(name, **variables):
    with open(os.path.join(PROMPTS_DIR, name + ".md"), encoding="utf-8") as f:
        tpl = Template(f.read())
    try:
        return tpl.substitute(**variables)
    except KeyError as e:
        raise KeyError(f"prompt 模板 {name}.md 缺少变量 {e}") from e


def load_style_skill(level):
    """去AI味规范注入文本（Humanizer skill）。level: 关/精简/完整。

    - 关：返回空串；
    - 精简（默认）：skills/humanizer/core.md 精简规则卡（每次调用约 +5K token）；
    - 完整：SKILL.md 正文（去 frontmatter）+ banned-words.md + structures.md
      全量规则表（约 +30K token，慎用）。
    结果按档位进程内缓存。
    """
    level = (level or "精简").strip()
    if level in ("", "关", "off", "none", "0"):
        return ""
    if level in _SKILL_CACHE:
        return _SKILL_CACHE[level]
    base = os.path.join(SKILLS_DIR, "humanizer")

    def read(*parts):
        with open(os.path.join(base, *parts), encoding="utf-8") as f:
            return f.read()

    if level in ("完整", "full", "2"):
        skill = read("SKILL.md")
        if skill.startswith("---") and skill.count("---") >= 2:
            skill = skill.split("---", 2)[2]
        text = "\n\n".join([skill, read("references", "banned-words.md"),
                            read("references", "structures.md")])
    else:
        text = read("core.md")
    text = ("【去AI味写作规范——正文必须遵守】以下规范只约束正文写作风格，"
            "不要输出任何检测报告、修改统计或修改说明。\n\n" + text)
    _SKILL_CACHE[level] = text
    return text
