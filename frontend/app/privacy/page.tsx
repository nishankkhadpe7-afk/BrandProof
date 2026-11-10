export const metadata = { title: "Privacy policy — BrandProof" };

export default function Privacy() {
  return (
    <div className="auth"><div className="auth-card" style={{ maxWidth: 680 }}>
      <h1>Privacy policy</h1>
      <p className="muted">Last updated 11 November 2026. BrandProof is a student project and demo.</p>
      <h2>What we store</h2>
      <p>Your name, email address and a hashed password; the brand guidelines, approved facts and content you upload to a workspace; and an activity log of actions taken in that workspace.</p>
      <h2>How it's used</h2>
      <p>Only to check content against your workspace's rules and facts, and to send account emails such as password resets and invitations. Content may be sent to AI providers (Google Gemini, with Groq as a backup) for optional checks when the workspace's server has it enabled. We don't sell data or use it for advertising.</p>
      <h2>Email</h2>
      <p>Account emails are sent through the Gmail API. BrandProof only requests permission to send email; it does not read your inbox.</p>
      <h2>Retention and deletion</h2>
      <p>Demo data may be reset at any time. To delete your account and data, email the address below.</p>
      <h2>Contact</h2>
      <p>niahankkhadpe2606@gmail.com</p>
    </div></div>
  );
}
