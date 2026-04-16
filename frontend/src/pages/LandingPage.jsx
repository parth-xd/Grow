import { useNavigate } from 'react-router-dom';

function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 overflow-hidden">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-gray-900 flex items-center justify-center">
              <span className="text-lg font-bold text-white">G</span>
            </div>
            <span className="text-xl font-semibold text-gray-900">Grow</span>
          </div>
          <button
            onClick={() => navigate('/login')}
            className="px-6 py-2 bg-gray-900 text-white font-medium rounded-lg hover:bg-gray-800 transition-colors"
          >
            Sign In
          </button>
        </div>
      </nav>

      {/* Hero Section */}
      <div className="relative max-w-6xl mx-auto px-6 py-32">
        <div className="text-center mb-16">
          <h1 className="text-5xl md:text-6xl font-bold mb-6 leading-tight text-gray-900">
            Trade Smarter<br />Not Harder
          </h1>
          <p className="text-lg text-gray-600 mb-12 max-w-2xl mx-auto leading-relaxed">
            AI-powered trading platform built for serious traders. Real-time analytics, backtesting, and intelligent signals to maximize returns.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="bg-gray-900 text-white font-semibold py-3 px-10 text-base rounded-lg hover:bg-gray-800 transition-colors inline-block"
          >
            Get Started for Free
          </button>
          <p className="text-gray-600 text-sm mt-6">No credit card. No BS. Just results.</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 py-20 border-t border-b border-gray-200">
          <StatItem value="10K+" label="Active Traders" icon="📈" />
          <StatItem value="₹50Cr+" label="Volume Traded" icon="💰" />
          <StatItem value="24/7" label="AI Monitoring" icon="🤖" />
        </div>
      </div>

      {/* Features Section */}
      <div className="relative py-24">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4 text-gray-900">Why Choose Grow?</h2>
            <p className="text-lg text-gray-600">Everything you need to trade like a pro</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <Feature
              icon="🧠"
              title="AI Signals"
              description="ML models trained on 10+ years of market data. Intelligent buy/sell recommendations updated in real-time."
            />
            <Feature
              icon="📊"
              title="Live Analytics"
              description="Track your P&L, win rate, and performance metrics. Beautiful interactive charts and deep insights."
            />
            <Feature
              icon="🛡️"
              title="Risk Control"
              description="Automated stop-loss, position sizing, and portfolio rebalancing. Protect your capital 24/7."
            />
            <Feature
              icon="⚡"
              title="Instant Execution"
              description="Real-time order execution. Integrated with major Indian brokers. Zero delays, maximum efficiency."
            />
            <Feature
              icon="📉"
              title="Backtesting"
              description="Test your strategies on historical data. Validate ideas before risking real capital."
            />
            <Feature
              icon="🔐"
              title="Enterprise Security"
              description="Bank-grade encryption. Your credentials never leave your device. Full compliance & transparency."
            />
          </div>
        </div>
      </div>

      {/* Stats Section */}
      <div className="relative py-20 border-t border-gray-200">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 text-center">
            <div>
              <div className="text-3xl font-bold text-gray-900 mb-2">98%</div>
              <p className="text-gray-600">Uptime SLA</p>
            </div>
            <div>
              <div className="text-3xl font-bold text-gray-900 mb-2">500ms</div>
              <p className="text-gray-600">Avg Execution Time</p>
            </div>
            <div>
              <div className="text-3xl font-bold text-gray-900 mb-2">256-bit</div>
              <p className="text-gray-600">Encryption</p>
            </div>
            <div>
              <div className="text-3xl font-bold text-gray-900 mb-2">Live</div>
              <p className="text-gray-600">Support</p>
            </div>
          </div>
        </div>
      </div>

      {/* CTA Section */}
      <div className="relative max-w-4xl mx-auto px-6 py-20">
        <div className="bg-gray-900 border border-gray-200 p-12 rounded-2xl text-center shadow-sm">
          <h2 className="text-4xl font-bold mb-4 text-white">Ready to Elevate Your Trading?</h2>
          <p className="text-lg text-gray-300 mb-10 max-w-2xl mx-auto">
            Join thousands of traders using Grow to make smarter, faster decisions with AI.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="bg-white text-gray-900 font-semibold py-3 px-10 text-base rounded-lg hover:bg-gray-100 transition-colors inline-block"
          >
            Start Trading Now
          </button>
        </div>
      </div>

      {/* Footer */}
      <footer className="relative border-t border-gray-200 py-16 mt-20">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12">
            <div>
              <h3 className="font-bold text-gray-900 mb-4">Product</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900 transition-colors">Features</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">Pricing</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">API</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-bold text-gray-900 mb-4">Company</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900 transition-colors">About</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">Blog</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">Careers</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-bold text-gray-900 mb-4">Legal</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900 transition-colors">Privacy</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">Terms</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">Compliance</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-bold text-gray-900 mb-4">Connect</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900 transition-colors">Twitter</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">Discord</a></li>
                <li><a href="#" className="hover:text-gray-900 transition-colors">GitHub</a></li>
              </ul>
            </div>
          </div>
          <div className="border-t border-gray-200 pt-8">
            <p className="text-center text-gray-600 text-sm">
              © 2026 Grow. Designed for traders. Built for results.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

function StatItem({ value, label, icon }) {
  return (
    <div className="text-center">
      <div className="text-4xl mb-3">{icon}</div>
      <div className="text-3xl font-bold text-gray-900 mb-2">{value}</div>
      <div className="text-gray-600">{label}</div>
    </div>
  );
}

function Feature({ icon, title, description }) {
  return (
    <div className="group bg-white border border-gray-200 p-8 rounded-xl hover:border-gray-300 transition-all hover:shadow-md h-full">
      <div className="text-4xl mb-4 group-hover:scale-110 transition-transform">{icon}</div>
      <h3 className="text-xl font-bold text-gray-900 mb-3">{title}</h3>
      <p className="text-gray-600 leading-relaxed">{description}</p>
    </div>
  );
}

export default LandingPage;
