/** Original reference artwork, used at the user's request. */
const drawings = [
  'bPUjFEu6s1lHYnZSOnTxqr9Xow',
  'DspFvEPbUghOeDaGe5DwYzd4DA',
  'WuueScTbRbasJC90gKIeGt7Xs',
  'RaEF8lerZWQnleg3Mfpc46Uv9qY',
  'zpAf7f7z9RuHy90fx2gSCXfcE2k',
];

export default function ArchitectureBackdrop() {
  return <div className="architecture-backdrop" aria-hidden="true">
    <div className="architecture-track">
      {[...drawings, drawings[0]].map((name, index) => <img
        key={index}
        src={`https://framerusercontent.com/images/${name}.webp?width=3000&height=1739`}
        alt=""
        width={3000}
        height={1739}
        fetchPriority={index === 0 ? 'high' : 'auto'}
        draggable={false}
      />)}
    </div>
  </div>;
}
