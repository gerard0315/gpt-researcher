# Deep Research 深度研究模式 - 代码运行逻辑详解

## 概述

GPT Researcher 的 **Deep Research（深度研究）** 模式是一种递归式的智能研究系统，它通过模拟人类研究者的思维方式，对主题进行多层级、多维度的深入探索。与传统的一次性搜索不同，Deep Research 采用树状结构进行探索，能够在"广度"和"深度"两个维度上同时展开研究。

---

## 核心概念

### 1. 广度（Breadth）
在每个研究层级上，系统会生成多个搜索查询，从不同角度探索主题。这相当于同时派遣多个研究员，每人负责一个研究方向。

### 2. 深度（Depth）
对于每个研究方向，系统会递归地深入挖掘，追踪线索、发现关联。这相当于研究员发现新的线索后继续深入调查。

### 3. 并发控制（Concurrency）
系统使用异步编程模式，可以并行处理多个研究路径，同时通过信号量限制并发数量，避免资源耗尽。

### 4. 双轨查询规划（Dual-lane Query Planning）【NEW】
系统引入了创新的**三轨查询规划器**，将查询分为三个轨道（Lane）：
- **Subject Lane（主题轨道）**：聚焦特定实体（公司、人物、产品等）的身份和事实验证
- **Concept Lane（概念轨道）**：探索行业、技术、市场等概念性信息
- **Intersection Lane（交叉轨道）**：研究主题与概念的交集（如「某公司在某行业的地位」）

这种分离确保既不会遗漏主体身份核实，也不会忽略行业背景信息。

---

## 双轨查询规划器详解（Dual-lane Query Planner）

### 概述

双轨查询规划器是 Deep Research 的新核心组件，通过**Stage A 分析**和**Stage B 生成**两个阶段，智能地将查询分配到三个不同的轨道：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    双轨查询规划器架构                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Stage A: 主题概念分析 (analyze_subject_and_concepts)               │
│  ════════════════════════════════════════════════════               │
│  输入: 用户查询 + 父查询 + 报告类型                                  │
│     ↓                                                               │
│  LLM 分析 → 提取:                                                   │
│    - intention: 查询意图 (funding/product/comparison等)            │
│    - subject_summary: 主题实体摘要                                  │
│    - concept_terms: 概念术语分类 (industry/technology/market等)    │
│    - recommended_lane_budget: LLM 推荐的轨道预算                    │
│     ↓                                                               │
│  缓存结果 (_STAGE_A_CACHE)                                          │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  轨道预算分配 (_allocate_lane_slots)                                │
│  ═══════════════════════════════════                                │
│  配置: QUERY_LANE_BUDGET = {subject: 40, concept: 40, intersection: 20}
│     ↓                                                               │
│  根据 max_iterations 计算各轨道查询数量                              │
│     ↓                                                               │
│  应用最小约束: MIN_CONCEPT_QUERIES=1, MIN_INTERSECTION_QUERIES=0     │
│     ↓                                                               │
│  输出: slots = {subject: 2, concept: 1, intersection: 0} (示例)      │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Stage B: 轨道查询生成 (generate_lane_queries)                      │
│  ═══════════════════════════════════════════                        │
│  输入: Stage A 分析结果 + 轨道预算                                    │
│     ↓                                                               │
│  Strategic LLM (gpt-5.2-pro) 生成:                                  │
│    - subject_queries: 主题相关查询                                   │
│    - concept_queries: 概念相关查询                                   │
│    - intersection_queries: 交叉查询                                  │
│     ↓                                                               │
│  Grounding (ground_lane_queries):                                   │
│    - Subject/Intersection: 添加强制锚点（域名/别名）                 │
│    - Concept: 保持自由，不强制锚点                                   │
│     ↓                                                               │
│  合并 (_merge_lane_queries) → 最终子查询列表                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 三种查询轨道

| 轨道 | 用途 | 锚点要求 | 示例查询 |
|-----|------|---------|---------|
| **Subject** | 验证主体身份、收集主体事实 | 强制包含域名/别名 | `OpenAI site:openai.com 最新融资` |
| **Concept** | 探索行业趋势、技术概念 | 无强制锚点 | `生成式 AI 市场规模 2024` |
| **Intersection** | 研究主体在概念领域的地位 | 强制包含锚点 | `OpenAI 在 AI 芯片领域的布局` |

### 查询锚点过滤（Query Anchoring）

系统会从查询中提取**锚点**（域名和别名），用于：

1. **生成阶段**：为 Subject 和 Intersection 轨道的查询强制添加锚点
2. **过滤阶段**：验证搜索结果是否与主题相关

```python
# 锚点提取示例
extract_query_anchors("https://openai.com/about OpenAI GPT-4")
# → {
#   "domains": ["openai.com"],
#   "aliases": ["OpenAI", "GPT-4"]
# }
```

搜索结果会根据锚点进行评分过滤：
- 域名匹配: +8 分
- 别名精确匹配: +4 分
- 别名 Token 匹配: +3 分
- site: 过滤器不匹配: -4 分

### 配置参数

| 参数名 | 环境变量 | 默认值 | 说明 |
|-------|---------|-------|------|
| `dual_lane_query_planner` | `DUAL_LANE_QUERY_PLANNER` | `False` | 是否启用双轨规划器 |
| `query_lane_budget` | `QUERY_LANE_BUDGET` | `{subject: 40, concept: 40, intersection: 20}` | 各轨道预算百分比 |
| `min_concept_queries` | `MIN_CONCEPT_QUERIES` | `1` | 最小概念查询数 |
| `min_intersection_queries` | `MIN_INTERSECTION_QUERIES` | `0` | 最小交叉查询数 |
| `use_llm_recommended_lane_budget` | `USE_LLM_RECOMMENDED_LANE_BUDGET` | `False` | 是否使用 LLM 推荐的预算 |

### 启用双轨规划器

```python
# 方式 1: 环境变量
export DUAL_LANE_QUERY_PLANNER=true
export QUERY_LANE_BUDGET='{"subject": 40, "concept": 40, "intersection": 20}'
export MIN_CONCEPT_QUERIES=1

# 方式 2: 配置文件
# config.yaml
dual_lane_query_planner: true
query_lane_budget:
  subject: 40
  concept: 40
  intersection: 20
min_concept_queries: 1
min_intersection_queries: 0

# 方式 3: 代码中
researcher = GPTResearcher(
    query="OpenAI 最新进展",
    report_type="deep",
    config_overrides={
        "dual_lane_query_planner": True,
        "query_lane_budget": {"subject": 40, "concept": 40, "intersection": 20}
    }
)
```

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    Deep Research 架构图                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────┐                                          │
│   │   GPTResearcher │  主研究员实例                             │
│   │   (report_type  │                                          │
│   │    = "deep")    │                                          │
│   └────────┬────────┘                                          │
│            │ 初始化                                             │
│            ▼                                                    │
│   ┌─────────────────┐                                          │
│   │DeepResearchSkill│  深度研究技能模块                         │
│   └────────┬────────┘                                          │
│            │ run()                                              │
│            ▼                                                    │
│   ┌─────────────────┐     ┌─────────────────┐                  │
│   │generate_research│────▶│  deep_research  │                  │
│   │    _plan()      │     │   (递归方法)     │                  │
│   └─────────────────┘     └────────┬────────┘                  │
│                                    │                            │
│                    ┌───────────────┼───────────────┐            │
│                    │               │               │            │
│                    ▼               ▼               ▼            │
│            ┌──────────┐    ┌──────────┐    ┌──────────┐        │
│            │ 查询 1   │    │ 查询 2   │    │ 查询 N   │        │
│            │(Breadth) │    │(Breadth) │    │(Breadth) │        │
│            └────┬─────┘    └────┬─────┘    └────┬─────┘        │
│                 │               │               │               │
│                 ▼               ▼               ▼               │
│            ┌──────────┐    ┌──────────┐    ┌──────────┐        │
│            │子研究员  │    │子研究员  │    │子研究员  │        │
│            │(GPTResearcher)│(GPTResearcher)│(GPTResearcher)│   │
│            └────┬─────┘    └────┬─────┘    └────┬─────┘        │
│                 │               │               │               │
│                 ▼               ▼               ▼               │
│            ┌──────────┐    ┌──────────┐    ┌──────────┐        │
│            │学习点+   │    │学习点+   │    │学习点+   │        │
│            │追踪问题  │    │追踪问题  │    │追踪问题  │        │
│            └────┬─────┘    └────┬─────┘    └────┬─────┘        │
│                 │               │               │               │
│                 └───────────────┼───────────────┘               │
│                                 │                               │
│                    ┌────────────┴────────────┐                  │
│                    │  Depth > 1 ? 递归深入   │                  │
│                    │  广度减半，深度减一      │                  │
│                    └─────────────────────────┘                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心代码文件

| 文件路径 | 作用 |
|---------|------|
| `gpt_researcher/skills/deep_research.py` | Deep Research 核心实现 |
| `gpt_researcher/agent.py` | 主研究员类，负责初始化和调度 |
| `gpt_researcher/skills/researcher.py` | 标准研究执行器（被子研究员使用） |
| `gpt_researcher/actions/query_processing.py` | 查询处理，含双轨规划器 |
| `gpt_researcher/config/variables/default.py` | 默认配置参数 |

---

## 运行流程详解

### 第一阶段：初始化

当用户创建 `GPTResearcher` 实例并设置 `report_type="deep"` 时：

```python
# gpt_researcher/agent.py
class GPTResearcher:
    def __init__(self, query, report_type="deep", ...):
        # ... 其他初始化 ...
        self.deep_researcher = None
        if report_type == ReportType.DeepResearch.value:  # "deep"
            self.deep_researcher = DeepResearchSkill(self)
```

系统会创建一个 `DeepResearchSkill` 实例，该实例包含以下关键配置：
- `breadth`: 每层的广度（默认：3-4）
- `depth`: 最大深度（默认：2）
- `concurrency_limit`: 并发限制（默认：2-4）

### 第二阶段：执行研究

调用 `conduct_research()` 方法时，系统检测到 deep 模式，切换到深度研究路径：

```python
# gpt_researcher/agent.py
async def conduct_research(self, on_progress=None):
    # 检测是否为深度研究模式
    if self.report_type == ReportType.DeepResearch.value and self.deep_researcher:
        return await self._handle_deep_research(on_progress)
    # ... 标准研究流程 ...

async def _handle_deep_research(self, on_progress=None):
    # 记录日志和配置
    await self._log_event("research", step="deep_research_start", ...)
    
    # 执行深度研究
    self.context = await self.deep_researcher.run(on_progress=on_progress)
    
    return self.context
```

### 第三阶段：深度研究主流程（DeepResearchSkill.run）

```python
# gpt_researcher/skills/deep_research.py
async def run(self, on_progress=None) -> str:
    # 1. 首先生成研究计划（生成几个追踪问题）
    follow_up_questions = await self.generate_research_plan(self.researcher.query)
    
    # 2. 将原始查询与追踪问题合并
    combined_query = f"""
    Primary subject (must remain fixed): {self.researcher.query}
    Potential follow-up questions (hypotheses, do not assume true):
    {"\n".join(follow_up_questions)}
    """
    
    # 3. 执行递归深度研究
    results = await self.deep_research(
        query=combined_query,
        breadth=self.breadth,
        depth=self.depth,
        on_progress=on_progress
    )
    
    # 4. 整合结果并返回
    return self.researcher.context
```

### 第四阶段：递归深度研究（deep_research）

这是 Deep Research 的核心算法，采用递归方式实现树状探索：

```python
async def deep_research(
    self,
    query: str,
    breadth: int,
    depth: int,
    learnings: List[str] = None,
    citations: Dict[str, str] = None,
    visited_urls: Set[str] = None,
    on_progress=None
) -> Dict[str, Any]:
    
    # 1. 生成搜索查询（广度维度）
    serp_queries = await self.generate_search_queries(query, num_queries=breadth)
    # 生成类似：
    # - "query": "量子计算最新进展 2024", "researchGoal": "了解最新技术突破"
    # - "query": "quantum computing applications", "researchGoal": "探索实际应用场景"
    
    # 2. 并发处理每个查询
    semaphore = asyncio.Semaphore(self.concurrency_limit)
    
    async def process_query(serp_query: Dict[str, str]):
        async with semaphore:  # 控制并发
            # 创建子研究员（嵌套的 GPTResearcher）
            researcher = GPTResearcher(
                query=serp_query['query'],
                report_type=ReportType.ResearchReport.value,  # 标准模式
                # ... 其他配置 ...
            )
            
            # 执行标准研究
            context = await researcher.conduct_research()
            
            # 提取学习点和追踪问题
            results = await self.process_research_results(
                query=serp_query['query'],
                context=context
            )
            
            # 递归深入（如果深度 > 1）
            if depth > 1:
                new_breadth = max(2, breadth // 2)  # 广度减半
                new_depth = depth - 1                # 深度减一
                
                # 构建下一层查询
                next_query = f"""
                Primary subject (must remain fixed): {self.researcher.query}
                Previous research goal: {result['researchGoal']}
                Follow-up questions: {' '.join(result['followUpQuestions'])}
                """
                
                # 递归调用
                deeper_results = await self.deep_research(
                    query=next_query,
                    breadth=new_breadth,
                    depth=new_depth,
                    learnings=all_learnings,
                    # ... 其他参数 ...
                )
                
            return results
    
    # 并发执行所有查询
    tasks = [process_query(q) for q in serp_queries]
    results = await asyncio.gather(*tasks)
```

### 第五阶段：查询处理（双轨规划器模式）

当启用 `dual_lane_query_planner=True` 时，系统使用三轨查询规划器：

```python
# gpt_researcher/actions/query_processing.py

async def generate_sub_queries(...):
    # 检测是否使用双轨规划器
    if getattr(cfg, "dual_lane_query_planner", False):
        return await _generate_sub_queries_dual_lane(...)
    
    # 否则使用传统规划器...

async def _generate_sub_queries_dual_lane(...):
    """双轨规划路径: Stage A 分析 + Stage B 轨道生成 + 合并"""
    
    # Stage A: 分析主题和概念
    analysis = await analyze_subject_and_concepts(...)
    # → 返回: {intention, subject_summary, concept_terms, recommended_lane_budget}
    
    # 计算轨道槽位分配
    slots = _allocate_lane_slots(
        budget={"subject": 40, "concept": 40, "intersection": 20},
        max_iterations=3,
        min_concept=1,
        min_intersection=0
    )
    # → 示例: {subject: 2, concept: 1, intersection: 0}
    
    # Stage B: 生成轨道查询
    lane_queries = await generate_lane_queries(analysis=analysis, lane_budget=slots, ...)
    # → 返回: {
    #   "subject": ["OpenAI site:openai.com 融资", "OpenAI 创始人动态"],
    #   "concept": ["生成式 AI 市场规模 2024"],
    #   "intersection": ["OpenAI 在 AI 芯片领域的布局"]
    # }
    
    # Grounding: 为 Subject/Intersection 添加强制锚点
    grounded_lanes = ground_lane_queries(lane_queries, original_query)
    
    # 合并为最终子查询列表
    merged = _merge_lane_queries(grounded_lanes, slots)
    return merged[:max_iterations]
```

#### 传统模式（默认）

如果未启用双轨规划器，使用传统查询生成方式：

```python
async def generate_search_queries(self, query: str, num_queries: int = 3) -> List[Dict[str, str]]:
    # 1. 获取工作查询（处理非英语查询）
    working_query = await get_working_query_for_planning(query, ...)
    
    # 2. 构建提示词，要求 LLM 生成查询
    messages = [
        {"role": "system", "content": "You are an expert researcher generating search queries..."},
        {"role": "user", "content": f"Given the following prompt, generate {num_queries} unique search queries..."}
    ]
    
    # 3. 调用 LLM
    response = await create_chat_completion(
        messages=messages,
        llm_provider=self.researcher.cfg.strategic_llm_provider,
        reasoning_effort=self.researcher.cfg.reasoning_effort,
        temperature=0.4
    )
    
    # 4. 解析并接地处理
    queries = parse_queries(response)
    grounded_queries = ground_generated_queries(generated_query_text, query, max_queries=num_queries)
    
    return grounded_queries
```

### 第六阶段：结果处理（process_research_results）

从研究结果中提取关键学习点和后续问题：

```python
async def process_research_results(self, query: str, context: str, num_learnings: int = 3):
    messages = [
        {"role": "system", "content": "You are an expert researcher analyzing search results."},
        {"role": "user", "content": f"""
            Given the following research results for the query '{query}', 
            extract key learnings and suggest follow-up questions.
            
            Format:
            - Learning [source_url]: <insight>
            - Question: <question>
        """}
    ]
    
    response = await create_chat_completion(...)
    
    # 解析响应
    learnings = []      # 关键发现
    questions = []      # 追踪问题
    citations = {}      # 引用来源
    
    for line in response.split('\n'):
        if line.startswith('Learning'):
            # 提取学习点和来源URL
            learnings.append(learning)
            citations[learning] = url
        elif line.startswith('Question'):
            questions.append(question)
    
    return {
        'learnings': learnings,
        'followUpQuestions': questions,
        'citations': citations
    }
```

### 第七阶段：结果整合

所有递归层级的结果会被汇总、去重、限制长度：

```python
# 收集所有层级的学习点
all_learnings = []
all_citations = {}
all_context = []

for result in results:
    all_learnings.extend(result['learnings'])
    all_citations.update(result['citations'])
    all_context.append(result['context'])

# 修剪上下文以限制词数（默认 25k 词）
final_context = trim_context_to_word_limit(all_context, max_words=25000)

# 整合为最终上下文
self.researcher.context = "\n".join(final_context)
self.researcher.visited_urls = results['visited_urls']
```

### 新增：搜索结果锚点过滤

当查询包含明确的主题锚点（域名或别名）时，系统会对搜索结果进行相关性过滤：

```python
# gpt_researcher/skills/researcher.py

def _filter_results_for_primary_subject(self, query, search_results):
    """根据查询锚点过滤搜索结果"""
    anchors = self._query_anchors  # 预提取的锚点
    
    for result in search_results:
        score, reasons = self._score_result_subject_relevance(
            query, result, anchors
        )
        # 评分规则:
        # - 域名匹配: +8 分
        # - 域名 Token 匹配: +2 分
        # - 别名精确匹配: +4 分
        # - 别名 Token 匹配: +3 分
        # - site: 过滤器不匹配: -4 分
    
    # 保留评分 >= 3 的结果
    kept = [result for score, _, result in scored_results if score >= 3]
    
    # 如果没有满足条件的，回退到最高分的前3个
    if not kept:
        kept = positive_results[:3]
    
    return kept, filter_metadata
```

这种过滤确保研究结果与主题高度相关，避免偏离用户的原始查询意图。

---

## 递归算法详解

Deep Research 的递归算法可以用以下伪代码描述：

```
function deep_research(query, breadth, depth):
    if depth == 0:
        return 当前查询的基础研究结果
    
    # 广度扩展：生成多个搜索查询
    queries = generate_search_queries(query, breadth)
    
    results = []
    for each query in queries (并行执行):
        # 执行搜索和研究
        context = conduct_research(query)
        
        # 提取学习点
        learnings = extract_learnings(context)
        
        # 深度挖掘：递归深入
        if depth > 1:
            deeper_results = deep_research(
                query = combine(query, learnings.followUpQuestions),
                breadth = max(2, breadth // 2),  # 每层广度减半
                depth = depth - 1                 # 深度递减
            )
            results.append(deeper_results)
        else:
            results.append(learnings)
    
    return merge(results)
```

### 递归参数变化示例

假设初始配置：`breadth=4`, `depth=2`

```
层级 1 (Depth=2):
  ├── 查询 1 (Breadth=4)
  │     └── 层级 2 (Depth=1, Breadth=2)
  │           ├── 子查询 1.1
  │           └── 子查询 1.2
  ├── 查询 2 (Breadth=4)
  │     └── 层级 2 (Depth=1, Breadth=2)
  ├── 查询 3 (Breadth=4)
  │     └── 层级 2 (Depth=1, Breadth=2)
  └── 查询 4 (Breadth=4)
        └── 层级 2 (Depth=1, Breadth=2)
```

总计：4 × 2 = 8 个叶子查询

---

## 进度追踪

Deep Research 提供实时进度回调：

```python
class ResearchProgress:
    def __init__(self, total_depth: int, total_breadth: int):
        self.current_depth = 1       # 当前深度层级
        self.total_depth = total_depth
        self.current_breadth = 0     # 当前完成的广度数量
        self.total_breadth = total_breadth
        self.current_query = None    # 当前处理的查询
        self.completed_queries = 0   # 完成的查询数
        self.total_queries = 0       # 总查询数

# 使用示例
def on_progress(progress):
    print(f"深度: {progress.current_depth}/{progress.total_depth}")
    print(f"广度: {progress.current_breadth}/{progress.total_breadth}")
    print(f"当前查询: {progress.current_query}")

researcher = GPTResearcher(query="...", report_type="deep")
context = await researcher.conduct_research(on_progress=on_progress)
```

---

## 模型配置架构

Deep Research 采用**三层模型架构**，根据不同的任务复杂度选择不同的模型：

### 三层模型架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    三层模型架构                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────────┐      │
│   │  FAST_LLM    - 快速模型   (轻量级任务)                │      │
│   │  gpt-4o      - 用于摘要、格式化等快速操作             │      │
│   │  Token Limit: 3000                                 │      │
│   └─────────────────────────────────────────────────────┘      │
│                          ▼                                      │
│   ┌─────────────────────────────────────────────────────┐      │
│   │  SMART_LLM   - 智能模型   (复杂推理)                  │      │
│   │  kimi-k2-turbo-preview  - 用于内容分析、推理         │      │
│   │  Token Limit: 6000                                 │      │
│   └─────────────────────────────────────────────────────┘      │
│                          ▼                                      │
│   ┌─────────────────────────────────────────────────────┐      │
│   │  STRATEGIC_LLM - 战略模型 (深度研究)                  │      │
│   │  gpt-5.2-pro   - 用于查询生成、研究规划              │      │
│   │  Token Limit: 4000, 支持 reasoning_effort           │      │
│   └─────────────────────────────────────────────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 默认模型配置

| 层级 | 配置项 | 默认模型 | 提供商 | 用途 |
|-----|-------|---------|-------|------|
| **Fast** | `FAST_LLM` | `openai:gpt-4o` | OpenAI | 快速文本处理、摘要、格式化 |
| **Smart** | `SMART_LLM` | `moonshot:kimi-k2-turbo-preview` | Moonshot | 内容理解、智能分析、报告生成 |
| **Strategic** | `STRATEGIC_LLM` | `bltcy:gpt-5.2-pro` | BLTCY | 查询生成、研究规划、深度推理 |

### 前端预置模型配置

系统提供以下预置模型配置（可在前端界面选择）：

```python
MODEL_CONFIGS = {
    "official_gpt52pro": {"llm": "openai:gpt-5.2-pro", "provider": "openai"},
    "bltcy_gpt52pro": {"llm": "bltcy:gpt-5.2-pro", "provider": "bltcy"},
    "official_gpt4o": {"llm": "openai:gpt-4o", "provider": "openai"},
    "kimi_k2_turbo": {"llm": "moonshot:kimi-k2-turbo-preview", "provider": "moonshot"},
}

DEFAULT_MODEL_CONFIG = {
    "fast": "official_gpt4o",
    "smart": "kimi_k2_turbo", 
    "strategic": "bltcy_gpt52pro"
}
```

### Deep Research 中的模型使用

在 Deep Research 模式中，各模型的具体分工：

```python
# 1. 查询生成阶段 - 使用 STRATEGIC_LLM
response = await create_chat_completion(
    messages=messages,
    llm_provider=self.researcher.cfg.strategic_llm_provider,  # bltcy
    model=self.researcher.cfg.strategic_llm_model,            # gpt-5.2-pro
    reasoning_effort=self.researcher.cfg.reasoning_effort,    # high
    temperature=0.4
)

# 2. 研究计划生成 - 使用 STRATEGIC_LLM + High reasoning
response = await create_chat_completion(
    llm_provider=self.researcher.cfg.strategic_llm_provider,
    model=self.researcher.cfg.strategic_llm_model,
    reasoning_effort=ReasoningEfforts.High.value,  # 高推理强度
    temperature=0.4
)

# 3. 结果处理/子研究员 - 使用 SMART_LLM
researcher = GPTResearcher(
    query=serp_query['query'],
    report_type=ReportType.ResearchReport.value,
    # 内部使用 SMART_LLM 进行内容分析
)
```

### 模型性能与成本对比

| 模型 | 提供商 | 特点 | 适用场景 | 预估成本* |
|-----|-------|------|---------|----------|
| **gpt-4o** | OpenAI | 速度快、性价比高 | 快速摘要、格式化 | $0.001-0.003 / 1K tokens |
| **kimi-k2-turbo** | Moonshot | 中文优化、长上下文 | 内容分析、报告生成 | 约 ¥0.01-0.03 / 1K tokens |
| **gpt-5.2-pro** | BLTCY | 强推理、支持 reasoning_effort | 查询生成、深度规划 | 根据提供商定价 |

\* 实际成本取决于使用量和 API 定价

---

## 配置参数

### 核心参数

| 参数名 | 环境变量 | 默认值 | 说明 |
|-------|---------|-------|------|
| `deep_research_breadth` | `DEEP_RESEARCH_BREADTH` | 3 | 每层的并行研究路径数 |
| `deep_research_depth` | `DEEP_RESEARCH_DEPTH` | 2 | 最大递归深度 |
| `deep_research_concurrency` | `DEEP_RESEARCH_CONCURRENCY` | 4 | 最大并发数 |
| `total_words` | `TOTAL_WORDS` | 1200 | 最终报告字数 |
| `fast_llm` | `FAST_LLM` | `openai:gpt-4o` | 快速任务模型 |
| `smart_llm` | `SMART_LLM` | `moonshot:kimi-k2-turbo-preview` | 智能分析模型 |
| `strategic_llm` | `STRATEGIC_LLM` | `bltcy:gpt-5.2-pro` | 战略推理模型 |
| `reasoning_effort` | `REASONING_EFFORT` | `medium` | 推理强度 (low/medium/high) |

### 双轨查询规划器参数（新）

| 参数名 | 环境变量 | 默认值 | 说明 |
|-------|---------|-------|------|
| `dual_lane_query_planner` | `DUAL_LANE_QUERY_PLANNER` | `False` | 是否启用双轨查询规划器 |
| `query_lane_budget` | `QUERY_LANE_BUDGET` | `{"subject": 40, "concept": 40, "intersection": 20}` | 各轨道预算分配（百分比） |
| `min_concept_queries` | `MIN_CONCEPT_QUERIES` | `1` | 最小概念查询数（当 max_iterations ≥ 2） |
| `min_intersection_queries` | `MIN_INTERSECTION_QUERIES` | `0` | 最小交叉查询数（当 max_iterations ≥ 3） |
| `use_llm_recommended_lane_budget` | `USE_LLM_RECOMMENDED_LANE_BUDGET` | `False` | 是否使用 LLM 推荐的轨道预算 |

### 配置方式

**方式 1：环境变量**
```bash
# Deep Research 参数
export DEEP_RESEARCH_BREADTH=4
export DEEP_RESEARCH_DEPTH=2
export DEEP_RESEARCH_CONCURRENCY=4
export TOTAL_WORDS=2500

# 模型配置
export FAST_LLM="openai:gpt-4o"
export SMART_LLM="moonshot:kimi-k2-turbo-preview"
export STRATEGIC_LLM="bltcy:gpt-5.2-pro"

# 推理强度
export REASONING_EFFORT="high"

# API Keys
export OPENAI_API_KEY="your-openai-key"
export KIMI_API_KEY="your-kimi-key"
export BLTCY_API_KEY="your-bltcy-key"

# 双轨查询规划器配置（可选）
export DUAL_LANE_QUERY_PLANNER=true
export QUERY_LANE_BUDGET='{"subject": 40, "concept": 40, "intersection": 20}'
export MIN_CONCEPT_QUERIES=1
export MIN_INTERSECTION_QUERIES=0
```

**方式 2：配置文件（YAML）**
```yaml
# config.yaml
# Deep Research 参数
deep_research_breadth: 4
deep_research_depth: 2
deep_research_concurrency: 4
total_words: 2500

# 模型配置
fast_llm: "openai:gpt-4o"
smart_llm: "moonshot:kimi-k2-turbo-preview"
strategic_llm: "bltcy:gpt-5.2-pro"

# 推理强度
reasoning_effort: "high"

# Token 限制
fast_token_limit: 3000
smart_token_limit: 6000
strategic_token_limit: 4000

# 双轨查询规划器配置（可选）
dual_lane_query_planner: true
query_lane_budget:
  subject: 40
  concept: 40
  intersection: 20
min_concept_queries: 1
min_intersection_queries: 0
use_llm_recommended_lane_budget: false
```

**方式 3：代码中动态配置**
```python
from gpt_researcher import GPTResearcher

# 方式 A: 通过配置文件
researcher = GPTResearcher(
    query="量子计算最新进展",
    report_type="deep",
    config_path="path/to/config.yaml"
)

# 方式 B: 运行时模型覆盖
researcher = GPTResearcher(
    query="量子计算最新进展",
    report_type="deep",
    model_overrides={
        "fast": "openai:gpt-4o-mini",      # 覆盖 Fast 模型
        "smart": "openai:gpt-4o",           # 覆盖 Smart 模型
        "strategic": "openai:o3-mini"       # 覆盖 Strategic 模型
    }
)

# 方式 C: 配置项覆盖
researcher = GPTResearcher(
    query="量子计算最新进展",
    report_type="deep",
    config_overrides={
        "deep_research_breadth": 5,
        "deep_research_depth": 3,
        "strategic_llm": "openai:gpt-5.2-pro",
        "reasoning_effort": "high"
    }
)

# 方式 D: 启用双轨查询规划器
researcher = GPTResearcher(
    query="OpenAI 最新融资情况",
    report_type="deep",
    config_overrides={
        "dual_lane_query_planner": True,
        "query_lane_budget": {"subject": 40, "concept": 40, "intersection": 20},
        "min_concept_queries": 1,
        "min_intersection_queries": 1
    }
)
```

---

## API Keys 配置

使用 Deep Research 需要配置以下 API Keys：

### 必需的 API Keys

| API Key | 用途 | 获取方式 |
|---------|------|---------|
| `OPENAI_API_KEY` | gpt-4o 模型调用 | [OpenAI Platform](https://platform.openai.com) |
| `KIMI_API_KEY` | kimi-k2-turbo 模型调用 | [Moonshot 开放平台](https://platform.moonshot.cn) |
| `BLTCY_API_KEY` | gpt-5.2-pro 模型调用 | BLTCY 平台 |

### 环境变量配置示例

```bash
# ~/.bashrc 或 ~/.zshrc

# OpenAI (用于 gpt-4o)
export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"

# Moonshot/Kimi (用于 kimi-k2-turbo-preview)
export KIMI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"

# BLTCY (用于 gpt-5.2-pro)
export BLTCY_API_KEY="xxxxxxxxxxxxxxxxxxxxxxxx"

# 可选：自定义基础 URL
export OPENAI_BASE_URL="https://api.openai.com/v1"
export KIMI_BASE_URL="https://api.moonshot.cn/v1"
```

### 运行时动态配置

```python
from gpt_researcher import GPTResearcher

# 使用 llm_provider_credentials 参数
researcher = GPTResearcher(
    query="量子计算最新进展",
    report_type="deep",
    llm_provider_credentials={
        "openai": "sk-openai-key",
        "moonshot": "sk-kimi-key",
        "bltcy": "bltcy-key"
    }
)
```

---

## 典型调用示例

### 基础用法

```python
from gpt_researcher import GPTResearcher
import asyncio

async def main():
    researcher = GPTResearcher(
        query="量子计算在药物研发中的最新应用",
        report_type="deep",  # 触发深度研究模式
    )
    
    # 执行研究
    context = await researcher.conduct_research()
    
    # 生成报告
    report = await researcher.write_report()
    print(report)

asyncio.run(main())
```

### 带进度追踪的用法

```python
async def main():
    def on_progress(progress):
        print(f"\r深度: {progress.current_depth}/{progress.total_depth} | "
              f"广度: {progress.current_breadth}/{progress.total_breadth} | "
              f"查询: {progress.completed_queries}/{progress.total_queries}", 
              end="")
    
    researcher = GPTResearcher(
        query="AI 在医疗诊断中的伦理问题",
        report_type="deep",
    )
    
    context = await researcher.conduct_research(on_progress=on_progress)
    report = await researcher.write_report()
    
    # 获取访问的 URL
    urls = researcher.get_source_urls()
    print(f"\n共访问 {len(urls)} 个来源")

asyncio.run(main())
```

---

## 性能与成本分析

### 时间复杂度

- **单次研究时间**：约 30-60 秒（取决于网络和内容）
- **总查询数**：约为 `breadth^depth` 的量级
- **总时间**：约 5-10 分钟（使用默认配置）

### API 成本估算

以 `o3-mini` 模型为例：

| 配置 | 估计查询数 | 估计 Token 数 | 估计成本 |
|-----|----------|-------------|---------|
| Breadth=3, Depth=2 | 9-12 次 | ~100K | $0.3-0.5 |
| Breadth=4, Depth=2 | 12-16 次 | ~150K | $0.4-0.7 |
| Breadth=4, Depth=3 | 20-30 次 | ~300K | $0.8-1.2 |

> 注：实际成本取决于查询复杂度和返回内容长度

---

## 错误处理与容错

Deep Research 具有以下容错机制：

1. **单点故障不影响整体**：如果某个查询失败，其他查询继续执行
2. **递归安全**：深度递减确保递归终止
3. **上下文长度限制**：自动修剪上下文防止超出模型限制
4. **并发控制**：信号量防止资源耗尽

```python
async def process_query(serp_query):
    try:
        # 执行研究
        context = await researcher.conduct_research()
        return results
    except Exception as e:
        # 记录错误但继续执行其他查询
        logger.error(f"Error processing query: {e}")
        return None  # 返回 None 会被过滤掉

# 过滤失败的查询
results = [r for r in results if r is not None]
```

---

## 最佳实践

### 1. 查询设计

- **从宽泛开始**：让系统自动探索具体方向
- **避免过度指定**：给 AI 更多探索空间
- **使用领域关键词**：帮助生成相关查询

### 2. 参数调优

| 场景 | Breadth | Depth | Concurrency |
|-----|---------|-------|-------------|
| 快速了解 | 2-3 | 1-2 | 4 |
| 深入研究 | 3-4 | 2-3 | 2-3 |
| 全面调研 | 4-5 | 3 | 2 |
| 资源受限 | 2 | 2 | 1 |

### 3. 成本控制

- 使用 `fast` 策略的 LLM 进行初始探索
- 限制 `total_words` 减少输出成本
- 监控 `on_progress` 及时发现问题

---

## 限制与注意事项

1. **时间消耗**：深度研究通常需要 5 分钟以上
2. **API 成本**：大量使用推理模型成本较高
3. **系统资源**：高并发设置需要更多内存和 CPU
4. **上下文限制**：总词数限制在 25K 以内
5. **递归深度**：建议不超过 3 层，避免指数级增长

---

## 总结

GPT Researcher 的 Deep Research 模式通过**递归 + 并发**的架构，结合**三层模型策略**（Fast/Smart/Strategic）和**双轨查询规划器**（Subject/Concept/Intersection），实现了对复杂主题的多维度深度探索。

### 核心优势

- 🌳 **树状探索**：同时在广度和深度上展开研究
- ⚡ **智能并发**：并行处理多个研究方向
- 🧠 **三层模型架构**：
  - **Fast** (`gpt-4o`): 快速文本处理和摘要
  - **Smart** (`kimi-k2-turbo`): 智能内容分析和报告生成
  - **Strategic** (`gpt-5.2-pro`): 深度查询生成和研究规划
- 🛣️ **双轨查询规划**（新）：
  - **Subject 轨道**：聚焦实体身份和事实验证
  - **Concept 轨道**：探索行业趋势和概念信息
  - **Intersection 轨道**：研究实体在概念领域的地位
- 📊 **实时进度**：全程可见的研究过程
- 🛡️ **容错设计**：部分失败不影响整体结果
- 🔍 **锚点过滤**：基于查询锚点的搜索结果相关性过滤

### 适用场景

- 需要全面了解一个主题
- 发现隐藏关联和深度洞察
- 初步学术研究
- 复杂问题的多角度分析

### 模型选择建议

| 需求 | 推荐配置 |
|-----|---------|
| 追求最佳效果 | 默认配置 (gpt-5.2-pro + kimi + gpt-4o) |
| 追求性价比 | strategic 降级为 gpt-4o |
| 中文内容为主 | 增加 kimi 使用比例 |
| 快速原型验证 | 全部使用 gpt-4o-mini |

### 双轨查询规划器使用建议

| 场景 | 是否启用 | 推荐预算配置 |
|-----|---------|-------------|
| 公司/产品调研 | ✅ 启用 | `{subject: 50, concept: 30, intersection: 20}` |
| 行业趋势分析 | ✅ 启用 | `{subject: 20, concept: 60, intersection: 20}` |
| 竞争对手对比 | ✅ 启用 | `{subject: 40, concept: 40, intersection: 20}` |
| 一般性知识查询 | ❌ 禁用 | 传统模式即可 |
| 快速初步探索 | ❌ 禁用 | 减少 API 调用次数 |
