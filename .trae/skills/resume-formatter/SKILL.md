---
name: "resume-formatter"
description: "专业简历排版助手，提供多套中文友好模板、结构化数据输入、HTML/PDF生成、岗位内容建议与检查清单。当用户需要制作/排版简历、生成简历模板、优化简历格式时调用。"
---

# 简历排版助手 (Resume Formatter)

专业的中文简历排版与生成工具，支持多种风格模板、结构化数据管理、一键生成可打印HTML。

---

## 一、快速开始流程

### Step 1: 确认用户需求
向用户确认以下信息（如未明确）：
1. **目标岗位**：AI产品经理 / 后端开发 / 前端 / 算法 / 其他
2. **偏好模板风格**：现代简约 / 商务正式 / 技术导向 / 学术研究 / 国际化
3. **简历页数**：单页（默认推荐）/ 多页
4. **语言**：中文 / 英文 / 中英双语

### Step 2: 收集简历数据
使用下方 **「结构化数据格式」** 引导用户提供简历内容，或让用户直接提供原始文本/Markdown，由你转换为标准结构。

### Step 3: 生成HTML简历
根据选择的模板风格，调用对应的模板生成函数，输出完整的HTML文件。

### Step 4: 质量检查
运行 **「简历检查清单」**，给出优化建议。

---

## 二、结构化数据格式（YAML）

所有简历内容统一转换为以下标准结构，便于模板复用：

```yaml
basic:
  name: "张三"
  title: "高级AI产品经理"
  avatar: ""                    # 可选：头像图片URL或base64
  location: "北京"
  email: "zhangsan@email.com"
  phone: "138-0000-0000"
  website: "https://zhangsan.dev"
  github: "github.com/zhangsan"
  linkedin: "linkedin.com/in/zhangsan"
  summary: "5年AI产品经验，主导过3个千万级用户的AI产品..."   # 2-3句个人简介

education:                     # 按时间倒序
  - school: "清华大学"
    degree: "硕士"
    major: "计算机科学与技术"
    period: "2018.09 - 2021.06"
    gpa: "3.8/4.0"             # 可选
    highlights:                 # 可选：课程/奖项/成就
      - "国家奖学金"
      - "主修：机器学习、NLP、产品设计"

experience:                    # 按时间倒序，建议3-5段
  - company: "字节跳动"
    position: "AI产品经理（高级）"
    period: "2023.03 - 至今"
    location: "北京"
    points:                     # 每段2-5点，用STAR法则，量化成果
      - "主导XX大模型产品从0到1搭建，DAU突破500万，用户留存提升30%"
      - "设计RAG检索增强方案，答案准确率从72%提升至91%"
      - "跨团队协调算法/工程/设计，推动3个核心功能按期上线"

projects:                      # 可选：突出的个人/开源项目
  - name: "智能简历优化Agent"
    role: "产品负责人 & 开发者"
    period: "2024.06 - 2024.08"
    tech_stack: "LangChain, RAG, FastAPI, Vue"
    link: "github.com/xxx/resume-agent"   # 可选
    points:
      - "基于LLM的简历内容优化系统，支持JD匹配度评分，GitHub 2k+ Stars"
      - "设计多Agent协作架构，包含JD分析、内容改写、排版生成3个核心Agent"

skills:
  categories:
    - name: "产品技能"
      items: ["需求分析", "PRD撰写", "用户研究", "A/B测试", "数据分析"]
    - name: "技术能力"
      items: ["Python", "SQL", "LangChain", "RAG架构", "Prompt Engineering"]
    - name: "工具软件"
      items: ["Figma", "Jira", "Notion", "Tableau", "Miro"]

awards:                        # 可选
  - name: "公司年度最佳产品奖"
    issuer: "字节跳动"
    date: "2024.01"
  - name: "全国大学生创新创业大赛金奖"
    issuer: "教育部"
    date: "2020.10"

certifications:                # 可选
  - name: "PMP项目管理专业认证"
    issuer: "PMI"
    date: "2023.06"

languages:                     # 可选
  - name: "中文"
    level: "母语"
  - name: "英语"
    level: "流利（CET-6 580分，可作为工作语言）"
```

---

## 三、模板风格库

### 模板 1: 现代简约（Modern）
**适用场景**：互联网公司、科技企业、产品/设计岗位  
**特点**：双栏布局、清爽配色、图标点缀、重点突出

### 模板 2: 商务正式（Professional）
**适用场景**：金融、咨询、传统行业、MBA申请  
**特点**：单栏布局、黑白灰配色、结构严谨、字体正式

### 模板 3: 技术导向（Tech Engineer）
**适用场景**：开发工程师、算法工程师、技术岗位  
**特点**：强调技能树、项目经历、GitHub链接、技术栈展示

### 模板 4: 学术研究（Academic CV）
**适用场景**：博士申请、科研岗位、高校教职  
**特点**：论文发表、研究经历、专利、学术会议

### 模板 5: 国际化（International）
**适用场景**：外企、海外求职、英文简历  
**特点**：符合欧美审美、标准英文术语、无照片（按当地习惯）

---

## 四、HTML模板生成器

### 公共基础：CSS打印优化
所有模板均内置以下打印规则，确保导出PDF效果完美：
```css
@media print {
  @page { size: A4; margin: 15mm 12mm; }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .no-print { display: none !important; }
  * { box-shadow: none !important; text-shadow: none !important; }
  page-break-inside: avoid;
}
```

---

### 模板 1: 现代简约 - HTML 代码

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{name} - 简历</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px; line-height: 1.6; color: #1f2937; background: #f5f5f5;
  }
  .resume {
    max-width: 210mm; min-height: 297mm; margin: 0 auto;
    background: #fff; display: grid; grid-template-columns: 230px 1fr;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
  }
  /* 左侧栏 */
  .sidebar {
    background: linear-gradient(160deg, #2563eb 0%, #1e40af 100%);
    color: #fff; padding: 32px 22px;
  }
  .sidebar .avatar {
    width: 110px; height: 110px; border-radius: 50%;
    border: 3px solid rgba(255,255,255,0.3);
    margin: 0 auto 18px; display: flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,0.1); font-size: 40px; font-weight: 600;
  }
  .sidebar h1 { font-size: 22px; text-align: center; margin-bottom: 4px; }
  .sidebar .title { font-size: 13px; text-align: center; opacity: 0.9; margin-bottom: 24px; }
  .sidebar-section { margin-bottom: 22px; }
  .sidebar-section h3 {
    font-size: 13px; font-weight: 600; margin-bottom: 10px;
    padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.25);
    letter-spacing: 1px;
  }
  .contact-item { font-size: 12px; margin-bottom: 8px; display: flex; align-items: flex-start; gap: 7px; word-break: break-all; }
  .contact-item .icon { width: 14px; flex-shrink: 0; opacity: 0.85; }
  .skill-cat { margin-bottom: 12px; }
  .skill-cat-name { font-size: 12px; opacity: 0.9; margin-bottom: 5px; }
  .skill-tags { display: flex; flex-wrap: wrap; gap: 5px; }
  .skill-tag {
    background: rgba(255,255,255,0.18); padding: 3px 9px; border-radius: 10px;
    font-size: 11px;
  }
  /* 右侧主内容 */
  .main-content { padding: 32px 30px; }
  .section { margin-bottom: 22px; }
  .section-title {
    font-size: 16px; font-weight: 700; color: #1e40af;
    margin-bottom: 12px; padding-bottom: 6px;
    border-bottom: 2px solid #2563eb; display: flex; align-items: center; gap: 8px;
  }
  .section-title::before {
    content: ''; width: 4px; height: 16px; background: #2563eb; border-radius: 2px;
  }
  .summary-text { color: #374151; line-height: 1.75; }
  /* 条目通用 */
  .entry { margin-bottom: 16px; position: relative; }
  .entry:last-child { margin-bottom: 0; }
  .entry-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; gap: 12px; }
  .entry-company, .entry-school { font-size: 14px; font-weight: 700; color: #111827; }
  .entry-position, .entry-degree { font-size: 13px; color: #2563eb; font-weight: 600; margin-right: auto; }
  .entry-period { font-size: 12px; color: #6b7280; white-space: nowrap; }
  .entry-location { font-size: 12px; color: #6b7280; white-space: nowrap; }
  .entry-subtitle { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
  .entry-points { padding-left: 18px; }
  .entry-points li {
    font-size: 12.5px; line-height: 1.65; margin-bottom: 3px;
    color: #374151; text-align: justify;
  }
  .entry-points li::marker { color: #2563eb; }
  .project-meta { font-size: 12px; color: #6b7280; margin-bottom: 6px; display: flex; gap: 10px; flex-wrap: wrap; }
  .tech-badges { display: inline-flex; flex-wrap: wrap; gap: 4px; }
  .tech-badge {
    background: #eff6ff; color: #1e40af; padding: 1px 7px; border-radius: 3px;
    font-size: 11px; font-family: Consolas, Monaco, monospace;
  }
  .award-item, .cert-item {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 5px 0; font-size: 12.5px; border-bottom: 1px dashed #e5e7eb; gap: 12px;
  }
  .award-item:last-child, .cert-item:last-child { border-bottom: none; }
  .award-name { font-weight: 600; color: #111827; }
  .award-issuer { color: #6b7280; font-size: 12px; }
  .award-date { color: #6b7280; font-size: 12px; white-space: nowrap; }
  .lang-item { margin-bottom: 7px; }
  .lang-name { font-weight: 600; font-size: 12.5px; display: inline-block; min-width: 50px; }
  .lang-level { color: #d1d5db; font-size: 12px; }

  @media print {
    @page { size: A4; margin: 0; }
    body { background: #fff; }
    .resume { box-shadow: none; }
  }
</style>
</head>
<body>
<div class="resume">
  <!-- 左侧 -->
  <aside class="sidebar">
    <div class="avatar">{name首字母或头像}</div>
    <h1>{name}</h1>
    <div class="title">{title}</div>

    <div class="sidebar-section">
      <h3>联系方式</h3>
      {contact_items}
    </div>

    <div class="sidebar-section">
      <h3>技能专长</h3>
      {skill_categories}
    </div>

    {if languages}
    <div class="sidebar-section">
      <h3>语言能力</h3>
      {language_items}
    </div>
    {/if}

    {if certifications}
    <div class="sidebar-section">
      <h3>证书资质</h3>
      {cert_items}
    </div>
    {/if}
  </aside>

  <!-- 右侧 -->
  <main class="main-content">
    {if summary}
    <section class="section">
      <div class="section-title">个人简介</div>
      <p class="summary-text">{summary}</p>
    </section>
    {/if}

    <section class="section">
      <div class="section-title">工作经历</div>
      {experience_entries}
    </section>

    {if projects}
    <section class="section">
      <div class="section-title">项目经历</div>
      {project_entries}
    </section>
    {/if}

    <section class="section">
      <div class="section-title">教育背景</div>
      {education_entries}
    </section>

    {if awards}
    <section class="section">
      <div class="section-title">荣誉奖项</div>
      {award_entries}
    </section>
    {/if}
  </main>
</div>
</body>
</html>
```

---

### 模板 2: 商务正式 - HTML 代码

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{name} - 个人简历</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: "SimSun", "Songti SC", "Times New Roman", "Noto Serif SC", serif;
    font-size: 12.5px; line-height: 1.7; color: #1a1a1a; background: #f3f3f3;
  }
  .resume {
    max-width: 210mm; min-height: 297mm; margin: 0 auto;
    background: #fff; padding: 28mm 22mm;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
  }
  /* 头部 */
  .header {
    text-align: center; padding-bottom: 16px;
    border-bottom: 2px solid #333; margin-bottom: 20px;
  }
  .header h1 {
    font-size: 30px; font-weight: 700; letter-spacing: 6px;
    margin-bottom: 6px; color: #1a1a1a;
  }
  .header .position {
    font-size: 15px; color: #555; letter-spacing: 2px; margin-bottom: 12px;
  }
  .header .contact {
    font-size: 12px; color: #444;
    display: flex; justify-content: center; flex-wrap: wrap; gap: 18px;
  }
  .header .contact span { white-space: nowrap; }
  .header .contact .sep { color: #bbb; }

  /* 通用区块 */
  .section { margin-bottom: 18px; page-break-inside: avoid; }
  .section-title {
    font-size: 14px; font-weight: 700; color: #1a1a1a;
    padding-bottom: 4px; border-bottom: 1px solid #333;
    margin-bottom: 10px; letter-spacing: 2px;
  }

  /* 简介 */
  .summary-text {
    text-indent: 2em; text-align: justify; color: #2a2a2a;
  }

  /* 条目 */
  .entry { margin-bottom: 14px; }
  .entry-header {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 3px; gap: 10px;
  }
  .entry-company {
    font-size: 13px; font-weight: 700; color: #1a1a1a;
  }
  .entry-position { font-size: 13px; font-weight: 600; color: #333; margin-right: auto; }
  .entry-school { font-size: 13px; font-weight: 700; }
  .entry-degree { font-size: 13px; font-weight: 600; color: #333; margin-right: auto; }
  .entry-period { font-size: 12px; color: #666; white-space: nowrap; }
  .entry-location { font-size: 12px; color: #666; white-space: nowrap; }
  .entry-sub {
    font-size: 12px; color: #555; margin-bottom: 4px;
    display: flex; gap: 15px; flex-wrap: wrap;
  }
  .entry-points { padding-left: 20px; }
  .entry-points li {
    text-align: justify; margin-bottom: 3px; color: #2a2a2a;
  }

  /* 项目 */
  .project-title-row {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 3px; gap: 10px;
  }
  .project-name { font-size: 13px; font-weight: 700; }
  .project-role { font-size: 12px; color: #555; margin-right: auto; }
  .project-meta {
    font-size: 11.5px; color: #666; margin-bottom: 5px;
    font-style: italic;
  }

  /* 技能表格样式 */
  .skills-table { width: 100%; border-collapse: collapse; }
  .skills-table td {
    padding: 6px 10px; border-bottom: 1px solid #e0e0e0; vertical-align: top;
    font-size: 12px;
  }
  .skills-table td:first-child {
    width: 90px; font-weight: 700; color: #333; white-space: nowrap;
    background: #fafafa;
  }

  /* 奖项、证书 */
  .simple-list li {
    padding: 4px 0; display: flex; justify-content: space-between;
    align-items: baseline; gap: 12px; border-bottom: 1px dotted #ddd;
  }
  .simple-list li:last-child { border-bottom: none; }
  .simple-list .left { flex: 1; }
  .simple-list .name { font-weight: 600; }
  .simple-list .sub { color: #666; font-size: 11.5px; margin-left: 8px; }
  .simple-list .date { color: #666; font-size: 11.5px; white-space: nowrap; }

  ul { list-style: disc; }

  @media print {
    @page { size: A4; margin: 0; }
    body { background: #fff; }
    .resume { box-shadow: none; }
  }
</style>
</head>
<body>
<div class="resume">
  <header class="header">
    <h1>{name}</h1>
    <div class="position">{title}</div>
    <div class="contact">
      {contact_items_with_separator}
    </div>
  </header>

  {if summary}
  <section class="section">
    <div class="section-title">自 我 评 价</div>
    <p class="summary-text">{summary}</p>
  </section>
  {/if}

  <section class="section">
    <div class="section-title">工 作 经 历</div>
    {experience_entries}
  </section>

  {if projects}
  <section class="section">
    <div class="section-title">项 目 经 历</div>
    {project_entries}
  </section>
  {/if}

  <section class="section">
    <div class="section-title">教 育 背 景</div>
    {education_entries}
  </section>

  <section class="section">
    <div class="section-title">专 业 技 能</div>
    {skills_table}
  </section>

  {if awards or certifications}
  <section class="section">
    <div class="section-title">荣 誉 证 书</div>
    {awards_and_certs_list}
  </section>
  {/if}
</div>
</body>
</html>
```

---

### 模板 3: 技术导向 - HTML 代码

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{name} - Resume</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: "JetBrains Mono", "SF Mono", Consolas, "PingFang SC", "Microsoft YaHei", monospace, sans-serif;
    font-size: 13px; line-height: 1.6; color: #0f172a;
    background: #0f172a;
  }
  .resume {
    max-width: 210mm; min-height: 297mm; margin: 0 auto;
    background: #ffffff; border: 3px solid #1e293b;
    display: grid; grid-template-columns: 1fr 260px;
  }
  /* 头部Header - 代码风格 */
  .top-header {
    grid-column: 1 / -1;
    background: #0f172a; color: #e2e8f0;
    padding: 26px 30px; border-bottom: 3px solid #334155;
  }
  .top-header .name-line {
    font-size: 26px; font-weight: 700; color: #38bdf8;
    font-family: "JetBrains Mono", Consolas, monospace;
  }
  .top-header .name-line::before { content: "const "; color: #94a3b8; font-size: 18px; }
  .top-header .name-line::after { content: " = {"; color: #94a3b8; font-size: 18px; margin-left: 4px; }
  .top-header .subtitle {
    color: #fbbf24; font-size: 14px; margin: 4px 0 0 64px;
  }
  .top-header .subtitle::before { content: "role: "; color: #94a3b8; }
  .top-header .contact-bar {
    margin-top: 14px; display: flex; flex-wrap: wrap; gap: 16px;
    margin-left: 64px; font-size: 12px;
  }
  .top-header .contact-bar span { color: #cbd5e1; }
  .top-header .contact-bar span::before { content: "// "; color: #64748b; }

  /* 主内容 */
  .main-col { padding: 26px 28px; }
  .side-col {
    padding: 26px 20px;
    background: #f8fafc; border-left: 2px solid #e2e8f0;
  }

  .section { margin-bottom: 22px; }
  .section-title {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 14px; font-weight: 700;
    color: #1e293b; margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
  }
  .section-title::before {
    content: "#"; color: #0ea5e9; font-weight: 700;
  }
  .section-title-code { font-size: 12px; color: #64748b; font-weight: normal; }

  /* 工作经历 */
  .experience-item {
    margin-bottom: 18px; padding-left: 14px;
    border-left: 2px solid #cbd5e1; position: relative;
  }
  .experience-item::before {
    content: ''; position: absolute; left: -6px; top: 4px;
    width: 10px; height: 10px; background: #0ea5e9;
    border-radius: 50%; border: 2px solid #fff;
  }
  .exp-head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 3px; gap: 10px; flex-wrap: wrap;
  }
  .exp-company {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 14px; font-weight: 700; color: #0f172a;
  }
  .exp-company::before { content: "@"; color: #0ea5e9; margin-right: 3px; }
  .exp-position { font-size: 13px; color: #0369a1; font-weight: 600; margin-right: auto; }
  .exp-period {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; color: #64748b; background: #f1f5f9;
    padding: 2px 8px; border-radius: 3px;
  }
  .exp-loc { font-size: 11px; color: #64748b; }
  .exp-points { padding-left: 18px; margin-top: 6px; }
  .exp-points li {
    margin-bottom: 4px; font-size: 12.5px;
    text-align: justify; color: #1e293b;
  }
  .exp-points li::marker { color: #0ea5e9; content: "▸ "; }
  .exp-points li strong { color: #dc2626; }
  .exp-points li code {
    background: #f1f5f9; padding: 1px 5px; border-radius: 3px;
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; color: #7c3aed;
  }

  /* 项目经历 */
  .project-card {
    border: 1px solid #e2e8f0; border-radius: 5px;
    padding: 12px 14px; margin-bottom: 12px;
    background: #fff; transition: border-color 0.2s;
  }
  .project-card:hover { border-color: #0ea5e9; }
  .project-head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 5px; gap: 10px;
  }
  .project-name {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-weight: 700; color: #111827;
  }
  .project-name::before { content: "$ "; color: #0ea5e9; }
  .project-link {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; color: #2563eb; text-decoration: none;
    background: #eff6ff; padding: 2px 7px; border-radius: 3px;
  }
  .project-role { font-size: 12px; color: #475569; margin-bottom: 5px; }
  .project-tech { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 7px; }
  .tech-chip {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 10.5px; padding: 2px 7px; border-radius: 3px;
    background: #0f172a; color: #38bdf8;
  }
  .project-desc { padding-left: 16px; }
  .project-desc li { margin-bottom: 3px; font-size: 12px; color: #334155; }
  .project-desc li::marker { color: #10b981; content: "✓ "; }

  /* 侧边栏 */
  .side-section { margin-bottom: 20px; }
  .side-title {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 13px; font-weight: 700; color: #0f172a;
    margin-bottom: 10px; padding-bottom: 5px;
    border-bottom: 2px solid #0ea5e9;
  }
  .side-title::before { content: "// "; color: #64748b; font-weight: normal; }

  /* 技能 */
  .skill-group { margin-bottom: 12px; }
  .skill-group-name {
    font-size: 11px; color: #475569; font-weight: 600;
    margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .skill-list { display: flex; flex-wrap: wrap; gap: 5px; }
  .skill-chip {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; padding: 3px 8px; border-radius: 3px;
    background: #0f172a; color: #e2e8f0;
  }
  .skill-chip.level-high { background: #065f46; color: #a7f3d0; border-left: 2px solid #10b981; }
  .skill-chip.level-mid { background: #78350f; color: #fde68a; border-left: 2px solid #f59e0b; }
  .skill-chip.level-basic { background: #334155; color: #cbd5e1; }

  /* 教育 */
  .edu-item { margin-bottom: 12px; }
  .edu-school { font-weight: 700; font-size: 13px; }
  .edu-detail { font-size: 11.5px; color: #475569; margin: 2px 0; }
  .edu-period {
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 10.5px; color: #64748b; background: #e2e8f0;
    padding: 1px 6px; border-radius: 2px; display: inline-block;
  }

  /* GitHub/开源贡献区 */
  .gh-stat {
    display: flex; justify-content: space-between;
    padding: 5px 0; font-size: 12px;
    border-bottom: 1px dashed #cbd5e1;
  }
  .gh-stat:last-child { border-bottom: none; }
  .gh-label { color: #475569; }
  .gh-value { font-family: "JetBrains Mono", Consolas, monospace; font-weight: 700; color: #0369a1; }

  @media print {
    @page { size: A4; margin: 0; }
    body { background: #fff; }
    .resume { border: none; }
  }
</style>
</head>
<body>
<div class="resume">
  <header class="top-header">
    <div class="name-line">{name}</div>
    <div class="subtitle">{title}</div>
    <div class="contact-bar">{contact_items}</div>
  </header>

  <div class="main-col">
    <section class="section">
      <div class="section-title">
        EXPERIENCE <span class="section-title-code">// 工作经历</span>
      </div>
      {experience_entries}
    </section>

    <section class="section">
      <div class="section-title">
        PROJECTS <span class="section-title-code">// 项目经历</span>
      </div>
      {project_entries}
    </section>
  </div>

  <div class="side-col">
    <div class="side-section">
      <div class="side-title">SKILLS / 技能栈</div>
      {skill_groups}
    </div>

    <div class="side-section">
      <div class="side-title">EDUCATION / 教育背景</div>
      {education_entries}
    </div>

    <div class="side-section">
      <div class="side-title">GITHUB STATS</div>
      {github_stats_or_awards}
    </div>
  </div>
</div>
</body>
</html>
```

---

## 五、岗位内容建议库

### AI产品经理 - 简历要点
1. **个人简介**：突出行业年限 + AI领域经验 + 核心产品成果 + 方法论掌握
2. **工作经历**：
   - 用数据量化：用户数、DAU、留存、转化率、营收
   - 体现AI能力：RAG、微调、Prompt、Agent、评估体系
   - 体现产品能力：从0到1、跨团队协作、需求洞察
3. **项目经历**：优先选大模型/AI相关项目，写清楚技术方案选型逻辑
4. **技能**：Prompt Engineering、RAG架构、模型评估、数据分析、A/B测试

### 后端开发工程师 - 简历要点
1. **工作经历**：
   - 量化指标：QPS、RT、可用性99.9X%、服务器成本降低X%
   - 突出架构：微服务、分布式、高并发、消息队列、缓存策略
   - 突出优化：SQL优化、JVM调优、重构带来的性能/代码质量提升
2. **项目经历**：写清系统设计、技术选型原因、攻克的难点
3. **技能分类**：语言 → 框架 → 中间件 → 数据库 → DevOps → 其他

### 算法工程师 - 简历要点
1. **强调**：论文/竞赛/专利、模型效果指标提升（准确率AUC等）、模型落地部署
2. **项目描述**：问题定义 → 数据处理 → 方案选型 → 实验对比 → 上线效果

---

## 六、简历检查清单（必过项）

调用此检查清单对生成的简历进行逐项审核：

### ✅ 内容质量
- [ ] 所有经历按**时间倒序**排列
- [ ] 每段工作经历**2-5个要点**，不堆砌
- [ ] 每个要点使用 **STAR法则**（情境-任务-行动-结果）
- [ ] 至少**70%的要点有量化数据**（数字/百分比/金额）
- [ ] 动词开头（主导、设计、优化、实现、推动、搭建...），避免"参与了""协助"
- [ ] 没有重复描述，每份简历**针对岗位定制**

### ✅ 格式排版
- [ ] **控制在1页以内**（10年以下经验），最多不超过2页
- [ ] 字体统一（标题/正文字号层级分明）
- [ ] 时间格式统一（如：2023.03 - 至今，不要混用不同格式）
- [ ] 行距 ≥ 1.4，四周留白 ≥ 12mm
- [ ] 没有孤行孤字（页首/页尾单独一行）
- [ ] 标点使用正确（中文用全角，代码/英文用半角）

### ✅ ATS友好（通过机器筛选）
- [ ] 使用**标准章节标题**（工作经历/教育背景/技能...），避免创意命名
- [ ] 不用图片、表格、文本框承载重要内容（ATS可能无法识别）
- [ ] 字体使用系统常规字体（避免艺术字体）
- [ ] PDF导出时**确保文字可复制**（不是图片扫描件）
- [ ] 包含JD中的**关键词**（技能、工具、行业术语）

### ✅ 基础信息
- [ ] 姓名 + 手机号 + 邮箱 **三项必填**
- [ ] 邮箱是专业的（不要用 partyboy123@xxx.com）
- [ ] 期望岗位明确写在标题位置
- [ ] 没有敏感信息（身份证号、婚姻状况、宗教信仰等）
- [ ] 照片（如果有）是**正式证件照/职业照**，不要用生活照自拍

---

## 七、使用示例对话

### 示例 1：从无到有生成简历
> **用户**：帮我做一份AI产品经理的简历，用现代简约风格  
> **你**：  
> Step 1. 调用此SKILL，按第二节YAML结构引导用户提供信息  
> Step 2. 信息收齐后，根据第四节「模板1: 现代简约」生成完整HTML  
> Step 3. 运行第六节「检查清单」给出优化建议  
> Step 4. 将HTML文件写入 `resume_output/{姓名}_简历.html`，告知用户用浏览器打开后 Ctrl+P 打印为PDF

### 示例 2：已有内容快速排版
> **用户**：我有一份Markdown简历，帮我排版成技术导向风格  
> **你**：  
> Step 1. 读取用户提供的Markdown内容  
> Step 2. 转换为第二节的标准YAML结构  
> Step 3. 使用「模板3: 技术导向」生成HTML  
> Step 4. 检查 + 写文件

---

## 八、文件输出规范

1. 生成的HTML简历统一存放路径：`项目根目录/resume_output/{姓名}_{岗位}_{模板风格}.html`
2. 同时生成一份对应的数据YAML文件：`resume_output/{姓名}_data.yaml`（便于后续修改）
3. 每次生成后附带**导出PDF指引**：
   > 💡 **PDF导出方法**：用浏览器（推荐Chrome/Edge）打开生成的HTML文件 → 按 `Ctrl+P` → 打印机选择「另存为PDF」 → 纸张尺寸选A4 → 边距选「无」或「默认」→ 勾选「背景图形」→ 保存即可

---

## 九、进阶优化技巧（可选提供）

1. **数字加粗**：HTML中所有关键数字（用户数、百分比、提升比例）用 `<strong>` 标签加粗，视觉上抓眼球
2. **关键词高亮**：与JD匹配的核心技能关键词，可以用浅底色+深色字轻微高亮
3. **一页控制**：如果内容略超一页，优先：缩小项目经历 → 合并早期工作经历要点 → 缩小正文字号至12px → 减小section间距
4. **中英双语**：同一页面上下分栏（上中文下英文），或生成两个独立文件
5. **版本管理**：每次修改简历时，用不同文件名保存版本，如 `张三_AI产品经理_字节跳动版.html`
