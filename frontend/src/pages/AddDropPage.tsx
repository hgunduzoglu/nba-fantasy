import { useState } from "react";
import type { League, Meta } from "../types";
import { FreeAgentsPage } from "./FreeAgentsPage";
import { WeekAddDropPage } from "./WeekAddDropPage";

type Menu = "ros" | "week";

/** İki ayrı add/drop menüsü: kalan sezonun değeri ve bu haftanın eşleşmesi. */
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
      </div>
      {menu === "ros" ? <FreeAgentsPage {...props} /> : <WeekAddDropPage {...props} />}
    </div>
  );
}
