"""
scraper/tests/fixtures/__init__.py

HTML fixture constants for scraper unit tests.
These are minimal but structurally valid HTML pages that mimic the real
source pages (Wellfound, generic careers pages, press releases).

No network calls are made — tests run fully offline against these strings.
"""

from __future__ import annotations

# ── Wellfound jobs page fixture ───────────────────────────────────────────────
# Mimics https://wellfound.com/company/acme-ai/jobs
# Wellfound renders job links as <a href="/jobs/<id>"> elements.
WELLFOUND_HTML_FIXTURE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Acme AI — Jobs on Wellfound</title>
</head>
<body>
  <header>
    <h1>Acme AI</h1>
    <nav><a href="/company/acme-ai">About</a> | <a href="/company/acme-ai/jobs">Jobs</a></nav>
  </header>
  <main>
    <section class="open-roles">
      <h2>Open Roles (5)</h2>

      <!-- Engineering roles — should be extracted and classified is_engineering=True -->
      <div class="job-card">
        <a href="/jobs/3001-senior-backend-engineer-acme-ai" class="job-link">
          Senior Backend Engineer
        </a>
        <span class="dept">Engineering</span>
        <span class="location">Remote · USA</span>
      </div>

      <div class="job-card">
        <a href="/jobs/3002-ml-engineer-acme-ai" class="job-link">
          ML Engineer — LLM Platform
        </a>
        <span class="dept">AI / ML</span>
        <span class="location">San Francisco, CA</span>
      </div>

      <div class="job-card">
        <a href="/jobs/3003-data-engineer-acme-ai" class="job-link">
          Data Engineer (dbt + Snowflake)
        </a>
        <span class="dept">Data</span>
        <span class="location">Remote · Global</span>
      </div>

      <!-- Non-engineering role — should NOT be classified as engineering -->
      <div class="job-card">
        <a href="/jobs/3004-account-executive-acme-ai" class="job-link">
          Account Executive
        </a>
        <span class="dept">Sales</span>
        <span class="location">New York, NY</span>
      </div>

      <!-- Another engineering role -->
      <div class="job-card">
        <a href="/jobs/3005-devops-engineer-acme-ai" class="job-link">
          DevOps Engineer — Kubernetes
        </a>
        <span class="dept">Infrastructure</span>
        <span class="location">Remote · EU</span>
      </div>
    </section>
  </main>
</body>
</html>"""


# ── Generic company careers page fixture ─────────────────────────────────────
# Mimics a direct company /careers page with h2/h3 job headings and
# anchor tags pointing to /careers/apply?role=... style URLs.
GENERIC_CAREERS_HTML_FIXTURE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Careers — Bluewave Technologies</title>
</head>
<body>
  <header>
    <h1>Join the Bluewave Team</h1>
  </header>
  <main>
    <section id="engineering">
      <h2>Engineering</h2>

      <div class="opening">
        <h3>Senior Software Engineer — Python / FastAPI</h3>
        <p>Join our platform team to build the next generation of our API infrastructure.</p>
        <a href="/careers/apply?role=senior-software-engineer-python">Apply Now</a>
      </div>

      <div class="opening">
        <h3>Frontend Engineer — React &amp; TypeScript</h3>
        <p>Help us build a polished, accessible product experience for our enterprise clients.</p>
        <a href="/careers/apply?role=frontend-engineer-react">Apply Now</a>
      </div>

      <div class="opening">
        <h3>Infrastructure Engineer — AWS / Terraform</h3>
        <p>Own our cloud infrastructure and reliability engineering practice.</p>
        <a href="/careers/apply?role=infrastructure-engineer-aws">Apply Now</a>
      </div>

      <div class="opening">
        <h3>Data Scientist — Machine Learning</h3>
        <p>Build and productionise ML models for our recommendation and risk systems.</p>
        <a href="/careers/apply?role=data-scientist-ml">Apply Now</a>
      </div>
    </section>

    <section id="non-engineering">
      <h2>Business Operations</h2>

      <div class="opening">
        <h3>Marketing Manager</h3>
        <p>Lead our demand generation and content marketing programs.</p>
        <a href="/careers/apply?role=marketing-manager">Apply Now</a>
      </div>

      <div class="opening">
        <h3>Customer Success Manager</h3>
        <p>Ensure our enterprise clients achieve their goals on Bluewave.</p>
        <a href="/careers/apply?role=customer-success-manager">Apply Now</a>
      </div>
    </section>
  </main>
</body>
</html>"""


# ── Press release fixture ─────────────────────────────────────────────────────
# Mimics a TechCrunch-style press release announcing a new CTO hire.
# Used to test press_extractor and leadership change signal detection.
PRESS_RELEASE_HTML_FIXTURE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Bluewave Technologies Appoints Dr. Amara Osei as Chief Technology Officer</title>
  <meta property="og:type" content="article">
  <meta property="article:published_time" content="2026-03-15T09:00:00Z">
</head>
<body>
  <article>
    <header>
      <h1>Bluewave Technologies Appoints Dr. Amara Osei as Chief Technology Officer</h1>
      <p class="byline">
        By TechBeat Staff &mdash;
        <time datetime="2026-03-15">March 15, 2026</time>
      </p>
    </header>

    <p>
      <strong>San Francisco, CA</strong> — Bluewave Technologies, the enterprise workflow
      automation platform, today announced the appointment of
      <strong>Dr. Amara Osei</strong> as its new Chief Technology Officer (CTO), effective
      April 1, 2026.
    </p>

    <p>
      Dr. Osei joins Bluewave from NeuralEdge Inc., where she served as VP of Engineering
      and led a team of 120 engineers across three continents. In her new role, she will
      oversee Bluewave's product and engineering organisation and drive the company's
      AI-first platform strategy.
    </p>

    <p>
      "We are thrilled to welcome Amara to the Bluewave leadership team," said James Kofi,
      CEO of Bluewave Technologies. "Her track record of scaling engineering organisations
      and shipping AI-powered products aligns perfectly with our roadmap."
    </p>

    <p>
      The appointment follows Bluewave's $18M Series B funding round announced in January
      2026 and signals an acceleration in the company's product development velocity.
    </p>

    <section class="about">
      <h2>About Bluewave Technologies</h2>
      <p>
        Bluewave Technologies provides enterprise workflow automation to over 300 B2B SaaS
        companies. Founded in 2021, the company is headquartered in San Francisco with
        engineering teams in Nairobi and Warsaw.
      </p>
    </section>
  </article>
</body>
</html>"""
