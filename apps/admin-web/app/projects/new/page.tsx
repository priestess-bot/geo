export default function NewProjectPage() {
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">项目创建向导</p>
          <h1>新建澳大利亚 GEO 项目</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            按步骤填完核心信息后，后台会创建项目、启动配置、品牌默认配置、评分权重和客户查看邀请。
          </p>
        </div>
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <form className="wizard" action="/projects" method="get">
        <section className="step">
          <div className="stepHeader">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="stepIndex">1</span>
              <div>
                <h2>租户与项目</h2>
                <p className="muted">确定内部归属和客户可见项目名称。</p>
              </div>
            </div>
          </div>
          <div className="formGrid">
            <label><span>租户名称</span><input name="tenant_name" placeholder="Design Partner AU" /></label>
            <label><span>项目名称</span><input name="project_name" placeholder="AU GEO Pilot" /></label>
          </div>
        </section>

        <section className="step">
          <div className="stepHeader">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="stepIndex">2</span>
              <div>
                <h2>品牌与官网</h2>
                <p className="muted">主域名会写入启动配置，并作为客户门户默认展示字段。</p>
              </div>
            </div>
            <button type="button">测试官网</button>
          </div>
          <div className="formGrid">
            <label><span>目标品牌</span><input name="target_brand" placeholder="ExampleBrand" /></label>
            <label><span>品类</span><input name="category" placeholder="DTC ecommerce products" /></label>
            <label><span>官网域名</span><input name="brand_official_domains" placeholder="example.com" /></label>
            <label><span>母公司</span><input name="brand_parent_company" placeholder="可选" /></label>
          </div>
        </section>

        <section className="step">
          <div className="stepHeader">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="stepIndex">3</span>
              <div>
                <h2>竞品范围</h2>
                <p className="muted">首期要求 3 到 5 个竞品，减少评分和对比维度漂移。</p>
              </div>
            </div>
          </div>
          <div className="formGrid">
            <label><span>竞品名称</span><textarea name="competitors" placeholder="Competitor A&#10;Competitor B&#10;Competitor C" /></label>
            <label><span>竞品域名</span><textarea name="competitor_domains" placeholder="competitor-a.com&#10;competitor-b.com&#10;competitor-c.com" /></label>
          </div>
        </section>

        <section className="step">
          <div className="stepHeader">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="stepIndex">4</span>
              <div>
                <h2>客户入口</h2>
                <p className="muted">客户邮箱用于生成 viewer 邀请；客户后续只用门户 token 访问单项目。</p>
              </div>
            </div>
          </div>
          <div className="formGrid">
            <label><span>客户邮箱</span><input name="customer_email" placeholder="customer@example.com" /></label>
            <label><span>项目 owner</span><input name="owner_user_id" placeholder="runtime-console" /></label>
          </div>
        </section>

        <section className="step">
          <div className="stepHeader">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="stepIndex">5</span>
              <div>
                <h2>采集与外部调用</h2>
                <p className="muted">涉及外部调用的配置提供测试入口；提交前不会保存 raw secret。</p>
              </div>
            </div>
            <button type="button">测试连接</button>
          </div>
          <div className="formGrid">
            <label><span>采集模式</span><select name="collection_mode"><option value="fixture">fixture</option><option value="api">api</option></select></label>
            <label><span>启动状态</span><select name="launch_status"><option value="draft">draft</option><option value="ready">ready</option><option value="active">active</option></select></label>
            <label><span>调度配置 JSON</span><textarea name="schedule" placeholder='{"cadence":"weekly"}' /></label>
            <label><span>连接器配置 JSON</span><textarea name="external_connectors" placeholder='{"openai":{"status":"configured"}}' /></label>
          </div>
          <div className="testRow">
            <span className="muted">提交调用 `POST /v1/projects/runtime/au/dtc-ecommerce`，后续会改成 Server Action 直接提交。</span>
            <button type="submit">创建项目</button>
          </div>
        </section>
      </form>
    </main>
  );
}
