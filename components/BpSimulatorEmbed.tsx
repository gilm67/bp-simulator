import React from "react";

const STREAMLIT_URL =
  "https://bp-simulator-j6q3pisfuvx8cpb57jtnnh.streamlit.app/?embed=true";

export default function BpSimulatorPage() {
  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-extrabold text-gray-900 sm:text-4xl">
            📈 Executive Partners – Business Plan Simulator
          </h1>
          <p className="mt-2 text-lg text-gray-600">
            Private & Confidential – Fill out your business plan projection and
            download a secure PDF report.
          </p>
        </div>

        {/* Embed iframe */}
        <div className="relative w-full" style={{ paddingTop: "75vh" }}>
          <iframe
            src={STREAMLIT_URL}
            className="absolute top-0 left-0 w-full h-full rounded-xl shadow-lg border border-gray-200"
            frameBorder="0"
            allowFullScreen
          />
        </div>

        {/* Disclaimer */}
        <p className="mt-4 text-center text-sm text-gray-500">
          Powered by Executive Partners · All data handled confidentially.
        </p>
      </div>
    </div>
  );
}
