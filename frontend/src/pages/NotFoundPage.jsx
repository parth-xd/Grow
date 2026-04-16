import { useNavigate } from 'react-router-dom';

function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="text-center">
        <h1 className="text-6xl font-bold text-indigo-400 mb-4">404</h1>
        <p className="text-2xl text-white mb-4">Page Not Found</p>
        <p className="text-gray-400 mb-8">The page you're looking for doesn't exist.</p>
        <button
          onClick={() => navigate('/dashboard')}
          className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-2 px-6 rounded-lg"
        >
          Go to Dashboard
        </button>
      </div>
    </div>
  );
}

export default NotFoundPage;
