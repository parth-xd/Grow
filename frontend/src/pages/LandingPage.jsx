import { useNavigate } from 'react-router-dom';

function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-white">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <span className="text-2xl font-bold text-gray-900">Groww AI Trading</span>
          <button
            onClick={() => navigate('/login')}
            className="btn-primary"
          >
            Sign In
          </button>
        </div>
      </nav>

      {/* Hero Section */}
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div className="text-center mb-16">
          <h1 className="text-5xl md:text-6xl font-bold text-gray-900 mb-6 leading-tight">
            Trade Smarter with <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">ML-Powered</span> Signals
          </h1>
          <p className="text-xl text-gray-600 mb-10 max-w-2xl mx-auto leading-relaxed">
            Use advanced machine learning models to predict market movements and execute trades with confidence. Real-time analytics, backtesting, and risk management in one platform.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="btn-primary py-4 px-10 text-lg font-semibold inline-block"
          >
            Get Started for Free
          </button>
          <p className="text-gray-500 text-sm mt-4">No credit card required</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 py-16 border-y border-gray-200">
          <StatItem value="5+" label="Years of Market Data" />
          <StatItem value="56" label="Successful Trades" />
          <StatItem value="4.15%" label="Average Return" />
        </div>
      </div>

      {/* Features Section */}
      <div className="bg-gray-50 py-20">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">Powerful Features</h2>
            <p className="text-xl text-gray-600">Everything you need to trade smarter</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <Feature
              number="01"
              title="ML Models"
              description="Advanced machine learning trained on 5+ years of market data. Continuously learns from market patterns."
            />
            <Feature
              number="02"
              title="Real-time Analytics"
              description="Live P&L tracking, performance metrics, and detailed trade analysis. Interactive charts and insights."
            />
            <Feature
              number="03"
              title="Paper Trading"
              description="Test your strategies risk-free before deploying real capital. Backtest with historical data."
            />
            <Feature
              number="04"
              title="Risk Management"
              description="Set stop-loss, take-profit, and position sizing rules. Protect your capital automatically."
            />
            <Feature
              number="05"
              title="Automated Trading"
              description="Let ML models execute trades automatically. 24/7 monitoring and execution with alerts."
            />
            <Feature
              number="06"
              title="Secure & Reliable"
              description="Bank-level security. Real-time database sync. API integration with major brokers."
            />
          </div>
        </div>
      </div>

      {/* CTA Section */}
      <div className="max-w-6xl mx-auto px-6 py-20">
        <div className="card p-12 text-center bg-gradient-to-br from-blue-50 to-white">
          <h2 className="text-4xl font-bold text-gray-900 mb-4">Ready to Transform Your Trading?</h2>
          <p className="text-xl text-gray-600 mb-8 max-w-2xl mx-auto">
            Join traders who are using AI to make smarter, faster decisions.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="btn-primary py-4 px-10 text-lg font-semibold inline-block"
          >
            Start Trading Now
          </button>
        </div>
      </div>

      {/* Footer */}
      <footer className="bg-gray-50 border-t border-gray-200 py-12">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-8">
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Product</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900">Features</a></li>
                <li><a href="#" className="hover:text-gray-900">Pricing</a></li>
                <li><a href="#" className="hover:text-gray-900">Backtesting</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Company</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900">About</a></li>
                <li><a href="#" className="hover:text-gray-900">Blog</a></li>
                <li><a href="#" className="hover:text-gray-900">Careers</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Legal</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900">Privacy</a></li>
                <li><a href="#" className="hover:text-gray-900">Terms</a></li>
                <li><a href="#" className="hover:text-gray-900">Contact</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Follow</h3>
              <ul className="space-y-2 text-gray-600 text-sm">
                <li><a href="#" className="hover:text-gray-900">Twitter</a></li>
                <li><a href="#" className="hover:text-gray-900">LinkedIn</a></li>
                <li><a href="#" className="hover:text-gray-900">GitHub</a></li>
              </ul>
            </div>
          </div>
          <div className="border-t border-gray-200 pt-8">
            <p className="text-center text-gray-600 text-sm">
              © 2026 Groww AI. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

function StatItem({ value, label }) {
  return (
    <div className="text-center">
      <div className="text-4xl font-bold text-blue-600 mb-2">{value}</div>
      <div className="text-gray-600">{label}</div>
    </div>
  );
}

function Feature({ number, title, description }) {
  return (
    <div className="card p-8 hover:shadow-lg transition-shadow h-full">
      <div className="text-4xl font-bold text-blue-500 mb-4">{number}</div>
      <h3 className="text-xl font-semibold text-gray-900 mb-3">{title}</h3>
      <p className="text-gray-600 leading-relaxed">{description}</p>
    </div>
  );
}

export default LandingPage;
