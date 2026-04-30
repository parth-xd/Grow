"use client";

import { Button } from "./button";
import Image from "next/image";

export function InstagramLink() {
  return (
    <a
      href="https://instagram.com/parrttthhh"
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center"
    >
      <Button className="rounded-full py-0 ps-0 border-wine-900/60 hover:border-wine-900 hover:bg-wine-900/10 transition-all duration-200">
        <div className="me-0.5 flex aspect-square h-full p-1.5">
          <Image
            className="h-auto w-full rounded-full"
            src="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=48&h=48&fit=crop"
            alt="Profile image"
            width={24}
            height={24}
            aria-hidden="true"
          />
        </div>
        <span className="text-white font-semibold">@groww</span>
      </Button>
    </a>
  );
}
