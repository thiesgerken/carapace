import pc from "picocolors";

console.log(pc.green(`hello, ${process.argv[2] ?? "world"}`));
