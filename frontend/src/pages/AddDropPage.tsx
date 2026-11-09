import { useState } from "react";
import type { League, Meta } from "../types";
import { DropPage } from "./DropPage";
import { FreeAgentsPage } from "./FreeAgentsPage";
import { WeekAddDropPage } from "./WeekAddDropPage";

type Menu = "ros" | "week" | "drop";

/** Add/drop menüleri: kalan sezonun değeri, bu haftanın eşleşmesi ve yalnız bırakma (IL dönüşü). */
export function AddDropPage(props: { meta: Meta; league: League; team: string; injuries: boolean }) {
  const [menu, setMenu] = useState<Menu>(() => {
    try {
      return (localStorage.getItem("tl.adddrop") as Menu) || "ros";
    } catch {
      return "ros";
    }
  });
  const pick = (m: Menu) => {
    setMenu(m);
    try {
      localStorage.setItem("tl.adddrop", m);
    } catch {
      /* özel pencere */
    }
  };
  return (
    <div className="stack">
      <div className="seg seg-main" role="group" aria-label="Add/drop menüsü">
        <button aria-pressed={menu === "ros"} onClick={() => pick("ros")}>Kalan sezon</button>
        <button aria-pressed={menu === "week"} onClick={() => pick("week")}>Bu hafta</button>
        <button aria-pressed={menu === "drop"} onClick={() => pick("drop")}
                title="IL'den dönen oyuncuya yer açarken kimi bırakmalı">Sadece bırak</button>
      </div>
      {menu === "ros" ? <FreeAgentsPage {...props} /> : menu === "week" ? <WeekAddDropPage {...props} /> : <DropPage {...props} />}
    </div>
  );
}
